"""Provider-isolated JSON LLM transport for Phase 6 grammar analysis."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

import requests
from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class LLMFailureDiagnostic:
    """Non-secret details that locate a provider failure without exposing the request."""

    stage: str
    exception_class: str
    http_status: int | None = None
    provider_error_type: str | None = None
    provider_error_code: str | None = None
    provider_message: str | None = None
    request_id: str | None = None
    retry_after: str | None = None
    parse_category: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "stage": self.stage,
                "exception_class": self.exception_class,
                "http_status": self.http_status,
                "provider_error_type": self.provider_error_type,
                "provider_error_code": self.provider_error_code,
                "provider_message": self.provider_message,
                "request_id": self.request_id,
                "retry_after": self.retry_after,
                "parse_category": self.parse_category,
            }.items()
            if value is not None
        }


class LLMServiceError(RuntimeError):
    """Base class for expected, user-safe provider failures."""

    def __init__(self, message: str, *, diagnostic: LLMFailureDiagnostic | None = None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


class LLMConfigurationError(LLMServiceError):
    pass


class LLMAuthenticationError(LLMServiceError):
    pass


class LLMRateLimitError(LLMServiceError):
    pass


class LLMTimeoutError(LLMServiceError):
    pass


class LLMNetworkError(LLMServiceError):
    pass


class LLMProviderError(LLMServiceError):
    pass


class LLMResponseError(LLMServiceError):
    pass


class LLMClient(Protocol):
    def request_json(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Request one validated-as-JSON provider response."""


@dataclass(frozen=True, slots=True)
class LLMSettings:
    provider: str
    api_key: str | None
    base_url: str | None
    model: str | None
    timeout_seconds: float = 20.0
    max_output_tokens: int = 800
    temperature: float = 0.0
    max_retries: int = 1

    @classmethod
    def from_environment(cls) -> "LLMSettings":
        load_dotenv()
        provider = os.getenv("LLM_PROVIDER", "openai_compatible").strip()
        api_key = os.getenv("LLM_API_KEY", "").strip() or None
        base_url = os.getenv("LLM_API_BASE_URL", "").strip() or None
        model = os.getenv("LLM_MODEL", "").strip() or None
        try:
            timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
            max_tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "800"))
            temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
            retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        except ValueError as exc:
            raise LLMConfigurationError("LLM numeric configuration is invalid") from exc
        if not provider:
            raise LLMConfigurationError("LLM_PROVIDER must not be empty")
        if timeout <= 0 or max_tokens <= 0 or not 0 <= temperature <= 2 or not 0 <= retries <= 1:
            raise LLMConfigurationError("LLM timeout, token, temperature, or retry settings are invalid")
        return cls(provider, api_key, base_url, model, timeout, max_tokens, temperature, retries)

    def validate_for_request(self) -> None:
        if not self.api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured")
        if not self.base_url:
            raise LLMConfigurationError("LLM_API_BASE_URL is not configured")
        if not self.model:
            raise LLMConfigurationError("LLM_MODEL is not configured")
        if self.provider != "openai_compatible":
            raise LLMConfigurationError(f"unsupported LLM_PROVIDER: {self.provider}")


class LLMService:
    """Small OpenAI-compatible adapter hidden behind the LLMClient protocol."""

    def __init__(
        self,
        settings: LLMSettings | None = None,
        *,
        session: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or LLMSettings.from_environment()
        self.session = session or requests.Session()
        self.sleep_fn = sleep_fn

    def request_json(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.settings.validate_for_request()
        if not system_prompt.strip():
            raise LLMResponseError("system prompt is empty")
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "max_completion_tokens": self.settings.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        # Current GPT-5.6 reasoning models only accept sampling parameters when
        # reasoning is disabled. Preserve the configured temperature explicitly.
        if self.settings.model.startswith("gpt-5.6"):
            payload["reasoning_effort"] = "none"
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        last_error: LLMServiceError | None = None
        for attempt in range(self.settings.max_retries + 1):
            retry_after_header: str | None = None
            try:
                response = self.session.post(url, headers=headers, json=payload, timeout=self.settings.timeout_seconds)
            except requests.Timeout:
                last_error = self._transport_error(LLMTimeoutError, "LLM request timed out")
            except requests.ConnectionError:
                last_error = self._transport_error(LLMNetworkError, "LLM network connection failed")
            except requests.RequestException:
                last_error = self._transport_error(LLMNetworkError, "LLM request failed")
            else:
                retry_after_header = response.headers.get("Retry-After")
                if response.status_code in (401, 403):
                    raise self._http_error(LLMAuthenticationError, "LLM authentication failed", response)
                if response.status_code == 429:
                    last_error = self._http_error(LLMRateLimitError, "LLM rate limit reached", response)
                elif response.status_code >= 500:
                    last_error = self._http_error(
                        LLMProviderError,
                        f"LLM provider server error ({response.status_code})",
                        response,
                    )
                elif response.status_code >= 400:
                    raise self._http_error(
                        LLMProviderError,
                        f"LLM provider rejected the request ({response.status_code})",
                        response,
                    )
                else:
                    return self._parse_response(response, response_schema)
            if attempt < self.settings.max_retries:
                retry_after = 0.0
                try:
                    retry_after = min(float(retry_after_header or "0"), 3.0)
                except ValueError:
                    retry_after = 0.0
                self.sleep_fn(retry_after or 0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _parse_response(response: Any, response_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise LLMResponseError(
                "LLM returned invalid JSON at the provider envelope",
                diagnostic=LLMService._response_diagnostic(
                    response, "provider_envelope_json", "provider_envelope"
                ),
            ) from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                "LLM provider response did not contain message content",
                diagnostic=LLMService._response_diagnostic(
                    response, "message_content_missing", "extraction"
                ),
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError(
                "LLM provider returned empty message content",
                diagnostic=LLMService._response_diagnostic(
                    response, "message_content_empty", "extraction"
                ),
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                "LLM message was not valid JSON",
                diagnostic=LLMService._response_diagnostic(
                    response, "message_content_json", "json"
                ),
            ) from exc
        if not isinstance(parsed, Mapping):
            raise LLMResponseError(
                "LLM JSON response must be an object",
                diagnostic=LLMService._response_diagnostic(
                    response, "message_content_not_object", "json"
                ),
            )
        return parsed

    @staticmethod
    def _transport_error(error_class: type[LLMServiceError], message: str) -> LLMServiceError:
        return error_class(
            message,
            diagnostic=LLMFailureDiagnostic(
                stage="transport",
                exception_class=error_class.__name__,
            ),
        )

    @staticmethod
    def _http_error(
        error_class: type[LLMServiceError], message: str, response: Any
    ) -> LLMServiceError:
        provider_type = provider_code = provider_message = None
        try:
            error_body = response.json().get("error", {})
            if isinstance(error_body, Mapping):
                provider_type = LLMService._safe_text(error_body.get("type"), 100)
                provider_code = LLMService._safe_text(error_body.get("code"), 100)
                provider_message = LLMService._safe_text(error_body.get("message"), 500)
        except (AttributeError, TypeError, ValueError):
            pass
        return error_class(
            message,
            diagnostic=LLMFailureDiagnostic(
                stage="provider_http",
                exception_class=error_class.__name__,
                http_status=response.status_code,
                provider_error_type=provider_type,
                provider_error_code=provider_code,
                provider_message=provider_message,
                request_id=LLMService._safe_text(response.headers.get("x-request-id"), 200),
                retry_after=LLMService._safe_text(response.headers.get("Retry-After"), 100),
            ),
        )

    @staticmethod
    def _response_diagnostic(response: Any, category: str, stage: str) -> LLMFailureDiagnostic:
        return LLMFailureDiagnostic(
            stage=stage,
            exception_class=LLMResponseError.__name__,
            http_status=getattr(response, "status_code", None),
            request_id=LLMService._safe_text(
                getattr(response, "headers", {}).get("x-request-id"), 200
            ),
            parse_category=category,
        )

    @staticmethod
    def _safe_text(value: Any, limit: int) -> str | None:
        if value is None:
            return None
        text = str(value).replace("\r", " ").replace("\n", " ")
        text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)
        return text[:limit]
