"""Typed models for personalized Finnish grammar exercises."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from app.models.grammar import ErrorType


SCHEMA_VERSION = "1.0"
EXERCISE_OPTION_COUNT = 4
MAX_QUESTION_CHARS = 500
MAX_OPTION_CHARS = 200
MAX_EXPLANATION_CHARS = 1_000


class ExerciseValidationError(ValueError):
    """Raised when a generated exercise violates the application schema."""


class ExerciseType(str, Enum):
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"


class ExerciseDifficulty(str, Enum):
    BASIC = "BASIC"


class ExerciseSource(str, Enum):
    LLM_GENERATED = "LLM_GENERATED"


class ExerciseSelectionSource(str, Enum):
    LEARNER_PROFILE = "LEARNER_PROFILE"
    USER_SELECTED = "USER_SELECTED"


# These are the categories for which the MVP can request a conservative,
# single-answer multiple-choice exercise. WORD_ORDER and OTHER are intentionally
# excluded because Finnish word order and open-ended categories are often
# compatible with more than one valid answer.
SUPPORTED_GENERATION_ERROR_TYPES: tuple[ErrorType, ...] = (
    ErrorType.CASE_ERROR,
    ErrorType.VERB_CONJUGATION,
    ErrorType.NOUN_INFLECTION,
    ErrorType.AGREEMENT,
    ErrorType.SPELLING,
)


def _required_string(value: Any, field: str, *, max_chars: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExerciseValidationError(f"{field} must be a non-empty string")
    if max_chars is not None and len(value) > max_chars:
        raise ExerciseValidationError(f"{field} exceeds the {max_chars}-character limit")
    return value


def _enum_value(value: Any, enum_type: type[Enum], field: str) -> Enum:
    if not isinstance(value, str):
        raise ExerciseValidationError(f"{field} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ExerciseValidationError(f"{field} must be one of: {allowed}") from exc


def normalize_answer(value: str) -> str:
    """Normalize only boundaries and Unicode composition for answer comparison."""

    if not isinstance(value, str):
        raise ExerciseValidationError("answer must be a string")
    return unicodedata.normalize("NFC", value).strip()


def _exercise_id_payload(
    *,
    schema_version: str,
    error_type: ErrorType,
    exercise_type: ExerciseType,
    difficulty: ExerciseDifficulty,
    question: str,
    options: tuple[str, ...],
    correct_answer: str,
    explanation: str,
    source: ExerciseSource,
    selection_source: ExerciseSelectionSource,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "error_type": error_type.value,
        "exercise_type": exercise_type.value,
        "difficulty": difficulty.value,
        "question": question,
        "options": list(options),
        "correct_answer": correct_answer,
        "explanation": explanation,
        "source": source.value,
        "selection_source": selection_source.value,
        "metadata": dict(metadata),
    }


def _exercise_id(**kwargs: Any) -> str:
    encoded = json.dumps(
        _exercise_id_payload(**kwargs),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Exercise:
    """One validated, deterministic-answer exercise."""

    schema_version: str
    exercise_id: str
    error_type: ErrorType
    exercise_type: ExerciseType
    difficulty: ExerciseDifficulty
    question: str
    options: tuple[str, ...]
    correct_answer: str
    explanation: str
    source: ExerciseSource
    selection_source: ExerciseSelectionSource
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ExerciseValidationError(f"schema_version must be {SCHEMA_VERSION}")
        _required_string(self.exercise_id, "exercise_id")
        _required_string(self.question, "question", max_chars=MAX_QUESTION_CHARS)
        _required_string(self.correct_answer, "correct_answer", max_chars=MAX_OPTION_CHARS)
        _required_string(self.explanation, "explanation", max_chars=MAX_EXPLANATION_CHARS)
        if not isinstance(self.error_type, ErrorType):
            raise ExerciseValidationError("error_type must be an approved ErrorType")
        if self.error_type not in SUPPORTED_GENERATION_ERROR_TYPES:
            raise ExerciseValidationError(
                f"error_type is not supported for automatic exercises: {self.error_type.value}"
            )
        if not isinstance(self.exercise_type, ExerciseType):
            raise ExerciseValidationError("exercise_type must be an approved ExerciseType")
        if not isinstance(self.difficulty, ExerciseDifficulty):
            raise ExerciseValidationError("difficulty must be an approved ExerciseDifficulty")
        if not isinstance(self.source, ExerciseSource):
            raise ExerciseValidationError("source must be an approved ExerciseSource")
        if not isinstance(self.selection_source, ExerciseSelectionSource):
            raise ExerciseValidationError("selection_source must be an approved value")
        if not isinstance(self.options, tuple) or len(self.options) != EXERCISE_OPTION_COUNT:
            raise ExerciseValidationError(
                f"multiple-choice exercises require exactly {EXERCISE_OPTION_COUNT} options"
            )
        normalized_options: list[str] = []
        for index, option in enumerate(self.options):
            normalized = normalize_answer(option)
            _required_string(normalized, f"options[{index}]", max_chars=MAX_OPTION_CHARS)
            normalized_options.append(normalized)
        if len(set(normalized_options)) != len(normalized_options):
            raise ExerciseValidationError("multiple-choice options must be unique")
        normalized_correct = normalize_answer(self.correct_answer)
        if normalized_options.count(normalized_correct) != 1:
            raise ExerciseValidationError("correct_answer must appear exactly once in options")
        if not isinstance(self.metadata, Mapping):
            raise ExerciseValidationError("metadata must be an object")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        expected_id = _exercise_id(
            schema_version=self.schema_version,
            error_type=self.error_type,
            exercise_type=self.exercise_type,
            difficulty=self.difficulty,
            question=self.question,
            options=tuple(self.options),
            correct_answer=self.correct_answer,
            explanation=self.explanation,
            source=self.source,
            selection_source=self.selection_source,
            metadata=self.metadata,
        )
        if self.exercise_id != expected_id:
            raise ExerciseValidationError("exercise_id must be a deterministic content hash")

    @classmethod
    def from_provider_dict(
        cls,
        value: Any,
        *,
        expected_error_type: ErrorType,
        expected_exercise_type: ExerciseType = ExerciseType.MULTIPLE_CHOICE,
        expected_difficulty: ExerciseDifficulty = ExerciseDifficulty.BASIC,
        selection_source: ExerciseSelectionSource = ExerciseSelectionSource.LEARNER_PROFILE,
        metadata: Mapping[str, Any] | None = None,
    ) -> "Exercise":
        """Build an application exercise from the provider-only response schema."""

        if not isinstance(value, Mapping):
            raise ExerciseValidationError("exercise response must be a JSON object")
        required = {
            "schema_version",
            "error_type",
            "exercise_type",
            "difficulty",
            "question",
            "options",
            "correct_answer",
            "explanation",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ExerciseValidationError(f"exercise response is missing fields: {', '.join(missing)}")
        unknown = sorted(set(value) - required)
        if unknown:
            raise ExerciseValidationError(
                f"exercise response contains unsupported fields: {', '.join(unknown)}"
            )
        if value["schema_version"] != SCHEMA_VERSION:
            raise ExerciseValidationError(f"schema_version must be {SCHEMA_VERSION}")
        error_type = _enum_value(value["error_type"], ErrorType, "error_type")
        exercise_type = _enum_value(value["exercise_type"], ExerciseType, "exercise_type")
        difficulty = _enum_value(value["difficulty"], ExerciseDifficulty, "difficulty")
        if error_type is not expected_error_type:
            raise ExerciseValidationError("provider exercise category does not match the selected weakness")
        if exercise_type is not expected_exercise_type:
            raise ExerciseValidationError("provider exercise type does not match the requested type")
        if difficulty is not expected_difficulty:
            raise ExerciseValidationError("provider exercise difficulty does not match the requested level")
        if not isinstance(value["options"], list):
            raise ExerciseValidationError("options must be a JSON list")
        options = tuple(value["options"])
        metadata_dict = dict(metadata or {})
        question = _required_string(value["question"], "question", max_chars=MAX_QUESTION_CHARS)
        correct_answer = _required_string(value["correct_answer"], "correct_answer", max_chars=MAX_OPTION_CHARS)
        explanation = _required_string(value["explanation"], "explanation", max_chars=MAX_EXPLANATION_CHARS)
        source = ExerciseSource.LLM_GENERATED
        exercise_id = _exercise_id(
            schema_version=SCHEMA_VERSION,
            error_type=error_type,
            exercise_type=exercise_type,
            difficulty=difficulty,
            question=question,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            source=source,
            selection_source=selection_source,
            metadata=metadata_dict,
        )
        return cls(
            schema_version=SCHEMA_VERSION,
            exercise_id=exercise_id,
            error_type=error_type,
            exercise_type=exercise_type,
            difficulty=difficulty,
            question=question,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            source=source,
            selection_source=selection_source,
            metadata=metadata_dict,
        )

    def answer_for(self, user_answer: str | int) -> str:
        """Resolve an A-D label or option text to the canonical option text."""

        if isinstance(user_answer, int) and not isinstance(user_answer, bool):
            if 0 <= user_answer < len(self.options):
                return self.options[user_answer]
            raise ExerciseValidationError("answer option index is out of range")
        if not isinstance(user_answer, str):
            raise ExerciseValidationError("answer must be an option label or text")
        normalized = normalize_answer(user_answer)
        if not normalized:
            raise ExerciseValidationError("answer must not be empty")
        labels = {chr(ord("A") + index): option for index, option in enumerate(self.options)}
        if normalized.upper() in labels and len(normalized) == 1:
            return labels[normalized.upper()]
        normalized_options = {normalize_answer(option): option for option in self.options}
        if normalized not in normalized_options:
            raise ExerciseValidationError("answer text must match one of the available options")
        return normalized_options[normalized]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "exercise_id": self.exercise_id,
            "error_type": self.error_type.value,
            "exercise_type": self.exercise_type.value,
            "difficulty": self.difficulty.value,
            "question": self.question,
            "options": list(self.options),
            "correct_answer": self.correct_answer,
            "explanation": self.explanation,
            "source": self.source.value,
            "selection_source": self.selection_source.value,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ExerciseAttemptResult:
    """Deterministic result of checking a learner's answer."""

    exercise_id: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    explanation: str

    def __post_init__(self) -> None:
        _required_string(self.exercise_id, "exercise_id")
        _required_string(self.user_answer, "user_answer")
        _required_string(self.correct_answer, "correct_answer")
        _required_string(self.explanation, "explanation", max_chars=MAX_EXPLANATION_CHARS)
        if not isinstance(self.is_correct, bool):
            raise ExerciseValidationError("is_correct must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "user_answer": self.user_answer,
            "correct_answer": self.correct_answer,
            "is_correct": self.is_correct,
            "explanation": self.explanation,
        }


def exercise_response_schema() -> dict[str, Any]:
    """Return the strict provider response schema used in the exercise prompt."""

    return {
        "type": "object",
        "required": [
            "schema_version",
            "error_type",
            "exercise_type",
            "difficulty",
            "question",
            "options",
            "correct_answer",
            "explanation",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": SCHEMA_VERSION},
            "error_type": {"type": "string", "enum": [item.value for item in SUPPORTED_GENERATION_ERROR_TYPES]},
            "exercise_type": {"type": "string", "enum": [ExerciseType.MULTIPLE_CHOICE.value]},
            "difficulty": {"type": "string", "enum": [ExerciseDifficulty.BASIC.value]},
            "question": {"type": "string"},
            "options": {
                "type": "array",
                "minItems": EXERCISE_OPTION_COUNT,
                "maxItems": EXERCISE_OPTION_COUNT,
                "items": {"type": "string"},
            },
            "correct_answer": {"type": "string"},
            "explanation": {"type": "string"},
        },
        "additionalProperties": False,
    }
