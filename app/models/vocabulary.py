"""Typed, JSON-serializable models for the Phase 8 vocabulary service."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class VocabularyStatus(str, Enum):
    FOUND = "found"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class VocabularySource:
    source_id: str
    name: str
    version: str
    url: str
    license: str
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ObservedFeatureAnalysis:
    features: dict[str, str]
    count: int


@dataclass(frozen=True)
class ObservedForm:
    form: str
    count: int
    features: dict[str, str] = field(default_factory=dict)
    feature_analyses: list[ObservedFeatureAnalysis] = field(default_factory=list)
    matches_query: bool = False


@dataclass(frozen=True)
class VocabularyExample:
    sentence: str
    source_id: str
    source_dataset: str


@dataclass(frozen=True)
class VocabularyAnalysis:
    lemma: str
    part_of_speech: str
    meanings: list[str] = field(default_factory=list)
    observed_forms: list[ObservedForm] = field(default_factory=list)
    example: VocabularyExample | None = None
    usage_note: str | None = None
    sources: list[VocabularySource] = field(default_factory=list)


@dataclass(frozen=True)
class VocabularyResult:
    query: str
    status: VocabularyStatus
    analyses: list[VocabularyAnalysis] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: str = "1.0"

    @property
    def lemma(self) -> str | None:
        """Return the lemma for an unambiguous result, otherwise ``None``."""

        return self.analyses[0].lemma if len(self.analyses) == 1 else None

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-friendly representation."""

        value = asdict(self)
        value["status"] = self.status.value
        return value
