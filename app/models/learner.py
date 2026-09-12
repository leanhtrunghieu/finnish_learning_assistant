"""Application models for persisted learner history and weakness profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.grammar import AnalysisStatus, ErrorType, LanguageMode


@dataclass(frozen=True, slots=True)
class StoredGrammarError:
    """One persisted error belonging to a stored grammar check."""

    id: int
    grammar_check_id: int
    error_index: int
    error_type: ErrorType
    error_text: str
    correction: str
    explanation: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "grammar_check_id": self.grammar_check_id,
            "error_index": self.error_index,
            "error_type": self.error_type.value,
            "error_text": self.error_text,
            "correction": self.correction,
            "explanation": self.explanation,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class StoredGrammarCheck:
    """A grammar result reconstructed from the SQLite history tables."""

    id: int
    learner_id: str
    schema_version: str
    original_sentence: str
    corrected_sentence: str
    is_correct: bool
    overall_explanation: str
    learning_tip: str
    language_mode: LanguageMode
    analysis_status: AnalysisStatus
    uncertainty_note: str | None
    created_at: str
    errors: tuple[StoredGrammarError, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "learner_id": self.learner_id,
            "schema_version": self.schema_version,
            "original_sentence": self.original_sentence,
            "corrected_sentence": self.corrected_sentence,
            "is_correct": self.is_correct,
            "overall_explanation": self.overall_explanation,
            "learning_tip": self.learning_tip,
            "language_mode": self.language_mode.value,
            "analysis_status": self.analysis_status.value,
            "uncertainty_note": self.uncertainty_note,
            "created_at": self.created_at,
            "errors": [error.to_dict() for error in self.errors],
        }


@dataclass(frozen=True, slots=True)
class LearnerWeakness:
    """A deterministic aggregate for one canonical error category."""

    error_type: ErrorType
    count: int
    percentage: float
    last_seen: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type.value,
            "count": self.count,
            "percentage": self.percentage,
            "last_seen": self.last_seen,
        }


@dataclass(frozen=True, slots=True)
class LearnerProfile:
    """Computed learner history summary; counters are derived, not stored."""

    learner_id: str
    total_checks: int
    total_errors: int
    weaknesses: tuple[LearnerWeakness, ...] = ()

    @property
    def primary_weakness(self) -> ErrorType | None:
        return self.weaknesses[0].error_type if self.weaknesses else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "total_checks": self.total_checks,
            "total_errors": self.total_errors,
            "primary_weakness": self.primary_weakness.value if self.primary_weakness else None,
            "weaknesses": [weakness.to_dict() for weakness in self.weaknesses],
        }
