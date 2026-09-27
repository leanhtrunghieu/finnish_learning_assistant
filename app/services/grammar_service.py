"""Finnish grammar orchestration above the provider-specific LLM transport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.grammar import (
    MAX_SENTENCE_CHARS,
    AnalysisStatus,
    GrammarResult,
    GrammarValidationError,
    LanguageMode,
    grammar_response_schema,
)
from app.services.llm_service import (
    LLMAuthenticationError,
    LLMClient,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServiceError,
    LLMTimeoutError,
    LLMFailureDiagnostic,
)


class GrammarServiceError(RuntimeError):
    """Expected grammar-service failure safe for a future UI to display."""

    def __init__(self, message: str, *, diagnostic: LLMFailureDiagnostic | None = None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "grammar_checker_prompt.txt"


class GrammarService:
    """Validate input, call the LLM client, and return a typed GrammarResult."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_path: Path = DEFAULT_PROMPT_PATH,
        max_sentence_chars: int = MAX_SENTENCE_CHARS,
        allow_repair_retry: bool = True,
    ) -> None:
        if max_sentence_chars < 1:
            raise ValueError("max_sentence_chars must be positive")
        self.llm_client = llm_client
        self.prompt_path = prompt_path
        self.max_sentence_chars = max_sentence_chars
        self.allow_repair_retry = allow_repair_retry

    def check_sentence(
        self,
        sentence: str,
        *,
        language_mode: LanguageMode = LanguageMode.STANDARD,
    ) -> GrammarResult:
        self._validate_input(sentence)
        if not isinstance(language_mode, LanguageMode):
            raise GrammarServiceError("language_mode must be a supported LanguageMode")
        try:
            prompt = self._load_prompt(language_mode)
        except OSError as exc:
            raise GrammarServiceError("grammar prompt could not be loaded") from exc
        payload = {"sentence": sentence, "language_mode": language_mode.value}
        try:
            raw = self.llm_client.request_json(
                system_prompt=prompt,
                user_payload=payload,
                response_schema=grammar_response_schema(),
            )
            return GrammarResult.from_dict(
                raw,
                expected_original=sentence,
                expected_language_mode=language_mode,
            )
        except (GrammarValidationError, LLMResponseError) as first_error:
            if not self.allow_repair_retry:
                raise self._service_error(first_error) from first_error
            repair_prompt = (
                prompt
                + "\nYour previous response was invalid. Return one JSON object matching the schema exactly. "
                + "Do not add commentary, markdown fences, or unsupported fields."
            )
            try:
                repaired = self.llm_client.request_json(
                    system_prompt=repair_prompt,
                    user_payload=payload,
                    response_schema=grammar_response_schema(),
                )
                return GrammarResult.from_dict(
                    repaired,
                    expected_original=sentence,
                    expected_language_mode=language_mode,
                )
            except (GrammarValidationError, LLMServiceError) as second_error:
                raise self._service_error(second_error) from second_error
        except LLMServiceError as first_error:
            raise self._service_error(first_error) from first_error

    def _load_prompt(self, language_mode: LanguageMode) -> str:
        template = self.prompt_path.read_text(encoding="utf-8")
        schema = json.dumps(grammar_response_schema(), ensure_ascii=False, indent=2)
        return template.replace("{{LANGUAGE_MODE}}", language_mode.value).replace("{{RESPONSE_SCHEMA}}", schema)

    def _validate_input(self, sentence: str) -> None:
        if not isinstance(sentence, str) or not sentence.strip():
            raise GrammarServiceError("Finnish sentence must not be empty")
        if len(sentence) > self.max_sentence_chars:
            raise GrammarServiceError(
                f"Finnish sentence exceeds the {self.max_sentence_chars}-character limit"
            )

    @staticmethod
    def _safe_message(error: Exception) -> str:
        if isinstance(error, GrammarValidationError):
            return "The grammar provider returned a response that failed schema validation."
        if isinstance(error, LLMConfigurationError):
            return "The grammar service is not configured. Set LLM_API_KEY, LLM_API_BASE_URL, and LLM_MODEL."
        if isinstance(error, LLMAuthenticationError):
            return "The grammar provider rejected authentication. Check the configured API key."
        if isinstance(error, LLMRateLimitError):
            return "The grammar provider is rate-limiting requests. Please try again later."
        if isinstance(error, LLMTimeoutError):
            return "The grammar provider timed out. Please try again later."
        return "The grammar provider is temporarily unavailable or returned an invalid response."

    @classmethod
    def _service_error(cls, error: Exception) -> GrammarServiceError:
        diagnostic = getattr(error, "diagnostic", None)
        if isinstance(error, GrammarValidationError):
            diagnostic = LLMFailureDiagnostic(
                stage="schema",
                exception_class=type(error).__name__,
                provider_message=cls._sanitize_validation_message(str(error)),
                parse_category="grammar_result_schema",
            )
        return GrammarServiceError(cls._safe_message(error), diagnostic=diagnostic)

    @staticmethod
    def _sanitize_validation_message(message: str) -> str:
        return message.replace("\r", " ").replace("\n", " ")[:500]


def check_sentence(sentence: str, *, language_mode: LanguageMode = LanguageMode.STANDARD) -> GrammarResult:
    """Convenience API for future callers; configuration is loaded from the environment."""
    from app.services.llm_service import LLMService

    return GrammarService(LLMService()).check_sentence(sentence, language_mode=language_mode)


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Check one Finnish sentence through the configured LLM")
    parser.add_argument("sentence")
    parser.add_argument("--colloquial-tolerant", action="store_true")
    args = parser.parse_args()
    mode = LanguageMode.COLLOQUIAL_TOLERANT if args.colloquial_tolerant else LanguageMode.STANDARD
    try:
        print(check_sentence(args.sentence, language_mode=mode).to_json())
    except GrammarServiceError as exc:
        print(f"Grammar check unavailable: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
