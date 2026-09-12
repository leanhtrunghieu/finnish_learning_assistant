"""Provider-isolated JSON LLM transport for Phase 6 grammar analysis."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

import requests
from dotenv import load_dotenv


class LLMServiceError(RuntimeError):
    """Base class for expected, user-safe provider failures."""


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
            "max_tokens": self.settings.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        last_error: LLMServiceError | None = None
        for attempt in range(self.settings.max_retries + 1):
            retry_after_header: str | None = None
            try:
                response = self.session.post(url, headers=headers, json=payload, timeout=self.settings.timeout_seconds)
            except requests.Timeout as exc:
                last_error = LLMTimeoutError("LLM request timed out")
            except requests.ConnectionError as exc:
                last_error = LLMNetworkError("LLM network connection failed")
            except requests.RequestException as exc:
                last_error = LLMNetworkError("LLM request failed")
            else:
                retry_after_header = response.headers.get("Retry-After")
                if response.status_code in (401, 403):
                    raise LLMAuthenticationError("LLM authentication failed")
                if response.status_code == 429:
                    last_error = LLMRateLimitError("LLM rate limit reached")
                elif response.status_code >= 500:
                    last_error = LLMProviderError(f"LLM provider server error ({response.status_code})")
                elif response.status_code >= 400:
                    raise LLMProviderError(f"LLM provider rejected the request ({response.status_code})")
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
            raise LLMResponseError("LLM returned invalid JSON at the provider envelope") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM provider response did not contain message content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("LLM provider returned empty message content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("LLM message was not valid JSON") from exc
        if not isinstance(parsed, Mapping):
            raise LLMResponseError("LLM JSON response must be an object")
        return parsed
