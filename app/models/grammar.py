"""Typed, provider-neutral grammar-analysis result models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
MAX_SENTENCE_CHARS = 500
MAX_ERRORS = 5


class GrammarValidationError(ValueError):
    """Raised when an LLM grammar response violates the application schema."""


class ErrorType(str, Enum):
    CASE_ERROR = "CASE_ERROR"
    VERB_CONJUGATION = "VERB_CONJUGATION"
    NOUN_INFLECTION = "NOUN_INFLECTION"
    WORD_ORDER = "WORD_ORDER"
    AGREEMENT = "AGREEMENT"
    SPELLING = "SPELLING"
    OTHER = "OTHER"


class LanguageMode(str, Enum):
    STANDARD = "STANDARD"
    COLLOQUIAL_TOLERANT = "COLLOQUIAL_TOLERANT"


class AnalysisStatus(str, Enum):
    COMPLETE = "COMPLETE"
    UNCERTAIN = "UNCERTAIN"


def _required_string(value: Any, field: str, *, max_chars: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GrammarValidationError(f"{field} must be a non-empty string")
    if max_chars is not None and len(value) > max_chars:
        raise GrammarValidationError(f"{field} exceeds the {max_chars}-character limit")
    return value


def _enum_value(value: Any, enum_type: type[Enum], field: str) -> Enum:
    if not isinstance(value, str):
        raise GrammarValidationError(f"{field} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise GrammarValidationError(f"{field} must be one of: {allowed}") from exc


@dataclass(frozen=True, slots=True)
class GrammarError:
    text: str
    correction: str
    error_type: ErrorType
    explanation: str
    confidence: float

    def __post_init__(self) -> None:
        text = _required_string(self.text, "error.text")
        correction = _required_string(self.correction, "error.correction")
        _required_string(self.explanation, "error.explanation", max_chars=1_000)
        if not isinstance(self.error_type, ErrorType):
            raise GrammarValidationError("error.error_type must be an approved ErrorType")
        if text == correction:
            raise GrammarValidationError("error.text and error.correction must differ")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise GrammarValidationError("error.confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise GrammarValidationError("error.confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", float(self.confidence))

    @classmethod
    def from_dict(cls, value: Any, *, original_sentence: str) -> "GrammarError":
        if not isinstance(value, Mapping):
            raise GrammarValidationError("each error must be an object")
        required = {"text", "correction", "error_type", "explanation", "confidence"}
        missing = sorted(required - set(value))
        if missing:
            raise GrammarValidationError(f"error is missing fields: {', '.join(missing)}")
        unknown = sorted(set(value) - required)
        if unknown:
            raise GrammarValidationError(f"error contains unsupported fields: {', '.join(unknown)}")
        text = _required_string(value["text"], "error.text")
        if text not in original_sentence:
            raise GrammarValidationError("error.text must occur in original_sentence")
        error_type = _enum_value(value["error_type"], ErrorType, "error.error_type")
        return cls(
            text=text,
            correction=value["correction"],
            error_type=error_type,
            explanation=value["explanation"],
            confidence=value["confidence"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "correction": self.correction,
            "error_type": self.error_type.value,
            "explanation": self.explanation,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class GrammarResult:
    original_sentence: str
    is_correct: bool
    corrected_sentence: str
    errors: tuple[GrammarError, ...]
    overall_explanation: str
    learning_tip: str
    language_mode: LanguageMode = LanguageMode.STANDARD
    analysis_status: AnalysisStatus = AnalysisStatus.COMPLETE
    uncertainty_note: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _required_string(self.original_sentence, "original_sentence", max_chars=MAX_SENTENCE_CHARS)
        _required_string(self.corrected_sentence, "corrected_sentence", max_chars=MAX_SENTENCE_CHARS)
        _required_string(self.overall_explanation, "overall_explanation", max_chars=2_000)
        _required_string(self.learning_tip, "learning_tip", max_chars=1_000)
        if not isinstance(self.language_mode, LanguageMode):
            raise GrammarValidationError("language_mode must be a supported LanguageMode")
        if not isinstance(self.analysis_status, AnalysisStatus):
            raise GrammarValidationError("analysis_status must be a supported AnalysisStatus")
        if not isinstance(self.is_correct, bool):
            raise GrammarValidationError("is_correct must be boolean")
        if not isinstance(self.errors, tuple):
            raise GrammarValidationError("errors must be a tuple internally")
        if len(self.errors) > MAX_ERRORS:
            raise GrammarValidationError(f"at most {MAX_ERRORS} errors are supported")
        if len({(error.text, error.correction, error.error_type) for error in self.errors}) != len(self.errors):
            raise GrammarValidationError("duplicate errors are not allowed")
        if self.is_correct:
            if self.errors:
                raise GrammarValidationError("a correct sentence must have an empty errors list")
            if self.corrected_sentence != self.original_sentence:
                raise GrammarValidationError("a correct sentence must not be silently rewritten")
        else:
            if not self.errors:
                raise GrammarValidationError("an incorrect sentence must contain at least one error")
            if self.corrected_sentence == self.original_sentence:
                raise GrammarValidationError(
                    "an incorrect sentence must provide a changed corrected_sentence"
                )
        if self.analysis_status is AnalysisStatus.UNCERTAIN:
            _required_string(self.uncertainty_note, "uncertainty_note", max_chars=1_000)
        elif self.uncertainty_note is not None:
            raise GrammarValidationError("uncertainty_note is only allowed for UNCERTAIN results")

    @classmethod
    def from_dict(
        cls,
        value: Any,
        *,
        expected_original: str | None = None,
        expected_language_mode: LanguageMode | None = None,
    ) -> "GrammarResult":
        if not isinstance(value, Mapping):
            raise GrammarValidationError("grammar response must be a JSON object")
        required = {
            "schema_version",
            "original_sentence",
            "language_mode",
            "analysis_status",
            "is_correct",
            "corrected_sentence",
            "errors",
            "overall_explanation",
            "learning_tip",
            "uncertainty_note",
        }
        missing = sorted(required - set(value))
        if missing:
            raise GrammarValidationError(f"grammar response is missing fields: {', '.join(missing)}")
        unknown = sorted(set(value) - required)
        if unknown:
            raise GrammarValidationError(f"grammar response contains unsupported fields: {', '.join(unknown)}")
        if value["schema_version"] != SCHEMA_VERSION:
            raise GrammarValidationError(f"schema_version must be {SCHEMA_VERSION}")
        original = _required_string(value["original_sentence"], "original_sentence", max_chars=MAX_SENTENCE_CHARS)
        if expected_original is not None and original != expected_original:
            raise GrammarValidationError("original_sentence does not match the submitted sentence")
        language_mode = _enum_value(value["language_mode"], LanguageMode, "language_mode")
        if expected_language_mode is not None and language_mode is not expected_language_mode:
            raise GrammarValidationError("language_mode does not match the requested mode")
        status = _enum_value(value["analysis_status"], AnalysisStatus, "analysis_status")
        if not isinstance(value["errors"], list):
            raise GrammarValidationError("errors must be a JSON list")
        if len(value["errors"]) > MAX_ERRORS:
            raise GrammarValidationError(f"at most {MAX_ERRORS} errors are supported")
        errors = tuple(GrammarError.from_dict(item, original_sentence=original) for item in value["errors"])
        return cls(
            schema_version=SCHEMA_VERSION,
            original_sentence=original,
            language_mode=language_mode,
            analysis_status=status,
            is_correct=value["is_correct"],
            corrected_sentence=value["corrected_sentence"],
            errors=errors,
            overall_explanation=value["overall_explanation"],
            learning_tip=value["learning_tip"],
            uncertainty_note=value["uncertainty_note"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "original_sentence": self.original_sentence,
            "language_mode": self.language_mode.value,
            "analysis_status": self.analysis_status.value,
            "is_correct": self.is_correct,
            "corrected_sentence": self.corrected_sentence,
            "errors": [error.to_dict() for error in self.errors],
            "overall_explanation": self.overall_explanation,
            "learning_tip": self.learning_tip,
            "uncertainty_note": self.uncertainty_note,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def grammar_response_schema() -> dict[str, Any]:
    """Return a compact JSON-schema-like description for provider prompts."""
    return {
        "type": "object",
        "required": [
            "schema_version",
            "original_sentence",
            "language_mode",
            "analysis_status",
            "is_correct",
            "corrected_sentence",
            "errors",
            "overall_explanation",
            "learning_tip",
            "uncertainty_note",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": SCHEMA_VERSION},
            "original_sentence": {"type": "string"},
            "language_mode": {"type": "string", "enum": [mode.value for mode in LanguageMode]},
            "analysis_status": {"type": "string", "enum": [status.value for status in AnalysisStatus]},
            "is_correct": {"type": "boolean"},
            "corrected_sentence": {"type": "string"},
            "errors": {
                "type": "array",
                "maxItems": MAX_ERRORS,
                "items": {
                    "type": "object",
                    "required": ["text", "correction", "error_type", "explanation", "confidence"],
                    "properties": {
                        "text": {"type": "string"},
                        "correction": {"type": "string"},
                        "error_type": {"type": "string", "enum": [error.value for error in ErrorType]},
                        "explanation": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "additionalProperties": False,
                },
            },
            "overall_explanation": {"type": "string"},
            "learning_tip": {"type": "string"},
            "uncertainty_note": {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    }
