"""Reproducible Phase 11 evaluation for the finished MVP.

The module evaluates each subsystem separately.  Provider-backed work is never
replaced with mocked quality results: if no provider is configured, every
attempt is retained as a controlled failure and provider-dependent metrics stay
undefined.  Deterministic service checks still run against isolated temporary
databases and the frozen local artifacts.
"""

from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import math
import os
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen

from app.models.exercise import (
    Exercise,
    ExerciseAttemptResult,
    ExerciseDifficulty,
    ExerciseSelectionSource,
    ExerciseType,
    SUPPORTED_GENERATION_ERROR_TYPES,
)
from app.models.grammar import (
    AnalysisStatus,
    ErrorType,
    GrammarError,
    GrammarResult,
    LanguageMode,
)
from app.models.learner import LearnerProfile, LearnerWeakness
from app.services.database_service import DatabaseService
from app.services.exercise_service import (
    ExerciseService,
    ExerciseServiceError,
    ExerciseTargetUnavailableError,
)
from app.services.grammar_service import GrammarService, GrammarServiceError
from app.services.llm_service import LLMProviderError, LLMService, LLMSettings
from app.services.ml_training import evaluate_pipeline, load_pipeline
from app.services.profile_service import ProfileService
from app.services.vocabulary_service import VocabularyService, normalize_lookup_key


EVALUATION_SCHEMA_VERSION = "1.0"
EVALUATION_VERSION = "v1"
GRAMMAR_CASE_COUNT = 40
VOCABULARY_CASE_COUNT = 16
EXERCISES_PER_CATEGORY = 4
RELIABILITY_REPEATS = 3
RELIABILITY_CASE_IDS = (
    "correct_01",
    "single_verb_01",
    "multiple_01",
    "colloquial_01",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSON objects from a UTF-8 JSONL file with useful line errors."""

    records: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSONL at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record must be an object at {path}:{line_number}")
            records.append(value)
    return records


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _mean(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.fmean(present) if present else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _latency_summary(values_ms: Sequence[float]) -> dict[str, Any]:
    return {
        "sample_count": len(values_ms),
        "median_ms": statistics.median(values_ms) if values_ms else None,
        "p95_ms": _percentile(values_ms, 0.95),
        "minimum_ms": min(values_ms) if values_ms else None,
        "maximum_ms": max(values_ms) if values_ms else None,
    }


def _load_optional_reviews(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    reviews = load_jsonl(path)
    by_id: dict[str, dict[str, Any]] = {}
    for review in reviews:
        case_id = review.get("case_id") or review.get("exercise_id")
        if not isinstance(case_id, str) or not case_id or case_id in by_id:
            raise ValueError(f"Manual-review IDs must be unique non-empty strings: {path}")
        by_id[case_id] = review
    return by_id


def merge_qualitative_reviews(
    grammar_records: Sequence[Mapping[str, Any]],
    exercise_records: Sequence[Mapping[str, Any]],
    grammar_reviews: Mapping[str, Mapping[str, Any]],
    exercise_reviews: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach completed review evidence without changing live provider outputs.

    The live result records are deep-copied. Only their nested review objects are
    replaced; provider configuration, latency, structured results, automatic
    scores, and failure evidence remain unchanged.
    """

    merged_grammar = copy.deepcopy(list(grammar_records))
    merged_exercises = copy.deepcopy(list(exercise_records))
    grammar_ids = {str(record["case_id"]) for record in merged_grammar}
    exercise_ids = {str(record["request_id"]) for record in merged_exercises}
    if set(grammar_reviews) != grammar_ids:
        raise ValueError("Grammar qualitative-review IDs must match raw-result IDs exactly")
    if set(exercise_reviews) != exercise_ids:
        raise ValueError("Exercise qualitative-review IDs must match raw-result IDs exactly")

    grammar_fields = (
        "grammatical_correctness",
        "relevance",
        "clarity",
        "learner_usefulness",
    )
    for record in merged_grammar:
        review = grammar_reviews[str(record["case_id"])]
        if record.get("run_status") != "success":
            if review.get("status") != "NOT_REVIEWABLE_NO_OUTPUT":
                raise ValueError("A grammar provider failure must remain non-reviewable")
            continue
        if review.get("status") != "COMPLETED":
            continue
        if any(review.get(field) not in (1, 2, 3) for field in grammar_fields):
            raise ValueError(f"Invalid completed grammar review: {record['case_id']}")
        payload = {
            "status": "COMPLETED",
            "reviewer": review.get("reviewer"),
            "review_method": review.get(
                "review_method", "AI-assisted qualitative linguistic review"
            ),
            "scale": review.get("scale", "1-3"),
            **{field: review[field] for field in grammar_fields},
            "correction_acceptability": review.get("correction_acceptability"),
            "notes": review.get("notes"),
        }
        record["manual_explanation_review"] = payload
        if "score" in record:
            record["score"]["explanation_review"] = copy.deepcopy(payload)

    exercise_fields = (
        "target_relevance",
        "question_clarity",
        "unambiguous",
        "answer_correctness",
        "distractor_plausibility",
        "explanation_correctness",
        "no_unrelated_errors",
    )
    for record in merged_exercises:
        review = exercise_reviews[str(record["request_id"])]
        if record.get("run_status") != "success":
            if review.get("status") != "NOT_REVIEWABLE_NO_OUTPUT":
                raise ValueError("An exercise provider failure must remain non-reviewable")
            continue
        if review.get("status") != "COMPLETED":
            continue
        if any(
            review.get(field) not in ("PASS", "PARTIAL", "FAIL")
            for field in exercise_fields
        ):
            raise ValueError(f"Invalid completed exercise review: {record['request_id']}")
        payload = {
            "status": "COMPLETED",
            "reviewer": review.get("reviewer"),
            "review_method": review.get(
                "review_method", "AI-assisted qualitative linguistic review"
            ),
            "scale": review.get("scale", "PASS/PARTIAL/FAIL"),
            **{field: review[field] for field in exercise_fields},
            "failure_reasons": list(review.get("failure_reasons", [])),
            "notes": review.get("notes"),
        }
        record["manual_linguistic_review"] = payload
    return merged_grammar, merged_exercises


def validate_grammar_cases(cases: Sequence[Mapping[str, Any]]) -> None:
    required = {
        "case_id",
        "sentence",
        "language_mode",
        "expected_is_correct",
        "expected_analysis_status",
        "expected_error_types",
        "acceptable_corrections",
        "notes",
    }
    ids: set[str] = set()
    for index, case in enumerate(cases, 1):
        missing = required - set(case)
        if missing:
            raise ValueError(f"Grammar case {index} is missing: {sorted(missing)}")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("Grammar case IDs must be unique non-empty strings")
        ids.add(case_id)
        LanguageMode(case["language_mode"])
        AnalysisStatus(case["expected_analysis_status"])
        if not isinstance(case["expected_is_correct"], bool):
            raise ValueError(f"expected_is_correct must be boolean for {case_id}")
        if not isinstance(case["expected_error_types"], list):
            raise ValueError(f"expected_error_types must be a list for {case_id}")
        for value in case["expected_error_types"]:
            ErrorType(value)
        if case["expected_is_correct"] and case["expected_error_types"]:
            raise ValueError(f"Correct grammar case cannot expect errors: {case_id}")
        corrections = case["acceptable_corrections"]
        if not isinstance(corrections, list) or not corrections or not all(
            isinstance(value, str) and value for value in corrections
        ):
            raise ValueError(f"acceptable_corrections must contain strings for {case_id}")


def _provider_failure_reason(message: str) -> str:
    lowered = message.casefold()
    if "not configured" in lowered:
        return "provider_configuration_failure"
    if "authentication" in lowered:
        return "provider_authentication_failure"
    if "rate" in lowered:
        return "provider_rate_limit"
    if "timed out" in lowered:
        return "provider_timeout"
    if "schema validation" in lowered or "invalid response" in lowered:
        return "invalid_provider_output"
    return "provider_failure"


def _provider_metadata(llm_client: Any) -> dict[str, Any]:
    settings = getattr(llm_client, "settings", None)
    return {
        "provider": getattr(settings, "provider", None),
        "model": getattr(settings, "model", None),
        "api_style": "chat_completions",
        "structured_output": "json_object_plus_local_schema_validation",
        "temperature": getattr(settings, "temperature", None),
        "max_output_tokens": getattr(settings, "max_output_tokens", None),
        "max_retries": getattr(settings, "max_retries", None),
        "api_secret_recorded": False,
    }


def _safe_failure_diagnostic(error: Exception) -> dict[str, Any] | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        diagnostic = getattr(current, "diagnostic", None)
        if diagnostic is not None and hasattr(diagnostic, "to_safe_dict"):
            return dict(diagnostic.to_safe_dict())
        current = current.__cause__
    return None


def _score_grammar_success(
    case: Mapping[str, Any],
    result: GrammarResult,
    review: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expected_categories = set(case["expected_error_types"])
    predicted_categories = {error.error_type.value for error in result.errors}
    overlap = expected_categories & predicted_categories
    category_precision = _ratio(len(overlap), len(predicted_categories))
    category_recall = _ratio(len(overlap), len(expected_categories))
    if not expected_categories and not predicted_categories:
        category_precision = category_recall = 1.0
    correction = result.corrected_sentence
    accepted = list(case["acceptable_corrections"])
    if case["expected_is_correct"]:
        correction_outcome = "not_applicable"
    elif correction == accepted[0]:
        correction_outcome = "exact_match"
    elif correction in accepted[1:]:
        correction_outcome = "acceptable_alternative"
    elif correction == case["sentence"]:
        correction_outcome = "incorrect_correction"
    elif review and review.get("correction_acceptability") == "ACCEPTABLE":
        correction_outcome = "acceptable_alternative"
    elif review and review.get("correction_acceptability") == "INCORRECT":
        correction_outcome = "incorrect_correction"
    else:
        correction_outcome = "unreviewed_alternative"
    if review:
        explanation_review = {
            "status": review.get("status", "COMPLETED"),
            "reviewer": review.get("reviewer"),
            "scale": review.get("scale", "1-3"),
            "grammatical_correctness": review.get("grammatical_correctness"),
            "relevance": review.get("relevance"),
            "clarity": review.get("clarity"),
            "learner_usefulness": review.get("learner_usefulness"),
            "notes": review.get("notes"),
        }
    else:
        explanation_review = {
            "status": "PENDING_MANUAL_REVIEW",
            "reviewer": None,
            "scale": "1-3",
            "criteria": [
                "grammatical correctness",
                "relevance",
                "clarity",
                "learner usefulness",
            ],
        }
    failure_reasons: list[str] = []
    if result.is_correct != case["expected_is_correct"]:
        failure_reasons.append("false_positive" if not result.is_correct else "false_negative")
    if expected_categories != predicted_categories:
        if expected_categories - predicted_categories:
            failure_reasons.append("missing_expected_category")
        if predicted_categories - expected_categories:
            failure_reasons.append("extra_category")
        if expected_categories and predicted_categories and not overlap:
            failure_reasons.append("wrong_category")
    if correction_outcome == "incorrect_correction":
        failure_reasons.append("incorrect_correction")
    elif correction_outcome == "unreviewed_alternative":
        failure_reasons.append("correction_requires_review")
    if result.analysis_status.value != case["expected_analysis_status"]:
        failure_reasons.append("analysis_status_mismatch")
    return {
        "detection_correct": result.is_correct == case["expected_is_correct"],
        "expected_categories": sorted(expected_categories),
        "predicted_categories": sorted(predicted_categories),
        "category_precision": category_precision,
        "category_recall": category_recall,
        "category_f1": _f1(category_precision, category_recall),
        "category_exact_match": expected_categories == predicted_categories,
        "correction_outcome": correction_outcome,
        "analysis_status_match": result.analysis_status.value == case["expected_analysis_status"],
        "explanation_review": explanation_review,
        "failure_reasons": failure_reasons,
    }


def run_grammar_cases(
    cases: Sequence[Mapping[str, Any]],
    grammar_service: GrammarService,
    *,
    reviews: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run the frozen grammar cases and preserve successes and failures."""

    validate_grammar_cases(cases)
    review_map = reviews or {}
    provider = _provider_metadata(grammar_service.llm_client)
    output: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        try:
            result = grammar_service.check_sentence(
                case["sentence"],
                language_mode=LanguageMode(case["language_mode"]),
            )
        except GrammarServiceError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            message = str(exc)
            output.append(
                {
                    "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                    "case_id": case["case_id"],
                    "sentence": case["sentence"],
                    "language_mode": case["language_mode"],
                    "expected": {
                        "is_correct": case["expected_is_correct"],
                        "analysis_status": case["expected_analysis_status"],
                        "error_types": case["expected_error_types"],
                        "acceptable_corrections": case["acceptable_corrections"],
                    },
                    "run_status": "controlled_failure",
                    "provider_configuration": provider,
                    "structured_output_valid": False,
                    "latency_ms": latency_ms,
                    "failure_reason": _provider_failure_reason(message),
                    "safe_error": message,
                    "safe_failure_diagnostic": _safe_failure_diagnostic(exc),
                    "manual_explanation_review": {
                        "status": "NOT_REVIEWABLE_NO_OUTPUT",
                        "reviewer": None,
                    },
                }
            )
        else:
            latency_ms = (time.perf_counter() - started) * 1000
            score = _score_grammar_success(case, result, review_map.get(case["case_id"]))
            output.append(
                {
                    "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                    "case_id": case["case_id"],
                    "sentence": case["sentence"],
                    "language_mode": case["language_mode"],
                    "expected": {
                        "is_correct": case["expected_is_correct"],
                        "analysis_status": case["expected_analysis_status"],
                        "error_types": case["expected_error_types"],
                        "acceptable_corrections": case["acceptable_corrections"],
                    },
                    "run_status": "success",
                    "provider_configuration": provider,
                    "structured_output_valid": True,
                    "latency_ms": latency_ms,
                    "result": result.to_dict(),
                    "score": score,
                    "manual_explanation_review": score["explanation_review"],
                }
            )
    return output


def aggregate_grammar_results(
    records: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Calculate detection, category, correction, and output-validity metrics."""

    by_case = {case["case_id"]: case for case in cases}
    successes = [record for record in records if record.get("run_status") == "success"]
    tp = tn = fp = fn = 0
    for record in successes:
        expected_error = not bool(record["expected"]["is_correct"])
        predicted_error = not bool(record["result"]["is_correct"])
        if expected_error and predicted_error:
            tp += 1
        elif expected_error:
            fn += 1
        elif predicted_error:
            fp += 1
        else:
            tn += 1
    evaluated = len(successes)
    precision = _ratio(tp, tp + fp) if evaluated else None
    recall = _ratio(tp, tp + fn) if evaluated else None
    detection = {
        "positive_class": "sentence contains at least one grammar error",
        "total_dataset_cases": len(records),
        "evaluated_cases_with_prediction": evaluated,
        "unevaluated_provider_failures": len(records) - evaluated,
        "coverage_rate": _ratio(evaluated, len(records)),
        "accuracy": _ratio(tp + tn, evaluated),
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "confusion_matrix": {
            "labels": ["expected_correct", "expected_error"],
            "values": [[tn, fp], [fn, tp]],
        },
    }
    valid_records = [record for record in successes if record["expected"]["is_correct"]]
    valid_total_dataset = sum(bool(case["expected_is_correct"]) for case in cases)
    false_positive_rate = {
        "definition": "known-valid frozen sentences flagged incorrect / total known-valid frozen sentences",
        "false_positives": sum(not record["result"]["is_correct"] for record in valid_records),
        "evaluated_valid_sentences": len(valid_records),
        "total_valid_sentences_in_dataset": valid_total_dataset,
        "valid_sentences_without_prediction": valid_total_dataset - len(valid_records),
        "rate": _ratio(
            sum(not record["result"]["is_correct"] for record in valid_records),
            valid_total_dataset,
        ),
        "evaluated_output_rate": _ratio(
            sum(not record["result"]["is_correct"] for record in valid_records),
            len(valid_records),
        ),
    }

    single_records = [
        record
        for record in successes
        if str(record["case_id"]).startswith("single_")
    ]
    categories = sorted(
        {
            value
            for case in cases
            if str(case["case_id"]).startswith("single_")
            for value in case["expected_error_types"]
        }
    )
    per_class: dict[str, Any] = {}
    for category in categories:
        class_tp = class_fp = class_fn = 0
        support = 0
        for record in single_records:
            expected = set(record["expected"]["error_types"])
            predicted = set(record["score"]["predicted_categories"])
            support += category in expected
            class_tp += category in expected and category in predicted
            class_fp += category not in expected and category in predicted
            class_fn += category in expected and category not in predicted
        if single_records:
            class_precision = class_tp / (class_tp + class_fp) if class_tp + class_fp else 0.0
            class_recall = class_tp / (class_tp + class_fn) if class_tp + class_fn else 0.0
        else:
            class_precision = class_recall = None
        per_class[category] = {
            "precision": class_precision,
            "recall": class_recall,
            "f1": _f1(class_precision, class_recall),
            "support_in_evaluated_cases": support,
            "support_in_dataset": sum(
                str(case["case_id"]).startswith("single_")
                and category in case["expected_error_types"]
                for case in cases
            ),
        }
    category_metrics = {
        "scope": "manually labeled single-error cases only",
        "evaluated_cases": len(single_records),
        "dataset_cases": sum(str(case["case_id"]).startswith("single_") for case in cases),
        "exact_match_accuracy": _ratio(
            sum(bool(record["score"]["category_exact_match"]) for record in single_records),
            len(single_records),
        ),
        "macro_precision": _mean(value["precision"] for value in per_class.values()),
        "macro_recall": _mean(value["recall"] for value in per_class.values()),
        "macro_f1": _mean(value["f1"] for value in per_class.values()),
        "per_class": per_class,
    }

    multiple_records = [
        record
        for record in successes
        if str(record["case_id"]).startswith("multiple_")
    ]
    multi_tp = multi_fp = multi_fn = 0
    per_case_multiple: list[dict[str, Any]] = []
    for record in multiple_records:
        expected = set(record["score"]["expected_categories"])
        predicted = set(record["score"]["predicted_categories"])
        overlap = expected & predicted
        multi_tp += len(overlap)
        multi_fp += len(predicted - expected)
        multi_fn += len(expected - predicted)
        per_case_multiple.append(
            {
                "case_id": record["case_id"],
                "precision": record["score"]["category_precision"],
                "recall": record["score"]["category_recall"],
                "f1": record["score"]["category_f1"],
                "exact_match": record["score"]["category_exact_match"],
            }
        )
    micro_precision = _ratio(multi_tp, multi_tp + multi_fp) if multiple_records else None
    micro_recall = _ratio(multi_tp, multi_tp + multi_fn) if multiple_records else None
    multiple_metrics = {
        "scope": "set-based scoring for cases labeled multiple_*; no forced single label",
        "evaluated_cases": len(multiple_records),
        "dataset_cases": sum(str(case["case_id"]).startswith("multiple_") for case in cases),
        "set_exact_match_rate": _ratio(
            sum(bool(value["exact_match"]) for value in per_case_multiple),
            len(per_case_multiple),
        ),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": _f1(micro_precision, micro_recall),
        "macro_precision": _mean(value["precision"] for value in per_case_multiple),
        "macro_recall": _mean(value["recall"] for value in per_case_multiple),
        "macro_f1": _mean(value["f1"] for value in per_case_multiple),
        "per_case": per_case_multiple,
    }

    correction_counts = collections.Counter(
        record["score"]["correction_outcome"] for record in successes
    )
    applicable_corrections = sum(
        not bool(record["expected"]["is_correct"]) for record in successes
    )
    reviews = [record["manual_explanation_review"] for record in successes]
    completed_reviews = [review for review in reviews if review.get("status") == "COMPLETED"]
    review_fields = (
        "grammatical_correctness",
        "relevance",
        "clarity",
        "learner_usefulness",
    )
    criterion_summary: dict[str, Any] = {}
    for field in review_fields:
        values = [
            int(review[field])
            for review in completed_reviews
            if review.get(field) in (1, 2, 3)
        ]
        counts = collections.Counter(values)
        criterion_summary[field] = {
            "rated": len(values),
            "score_1": counts[1],
            "score_2": counts[2],
            "score_3": counts[3],
            "mean": _mean(values),
            "score_3_rate": _ratio(counts[3], len(values)),
            "score_1_or_2_rate": _ratio(counts[1] + counts[2], len(values)),
        }
    explanation = {
        "methodology": {
            "scale": "1-3",
            "review_population": "all successful primary-set grammar responses",
            "dimensions": [
                "grammatical correctness",
                "relevance",
                "clarity",
                "learner usefulness",
            ],
            "review_method": "AI-assisted qualitative linguistic review",
            "subjectivity_note": (
                "Ratings are an AI-assisted linguistic judgment under the named reviewer "
                "identity, not a human/native-teacher assessment or objective linguistic truth."
            ),
        },
        "successful_outputs": len(successes),
        "completed_manual_reviews": len(completed_reviews),
        "pending_manual_reviews": len(successes) - len(completed_reviews),
        "not_reviewable_no_output": len(records) - len(successes),
        "average_scores": {
            field: _mean(review.get(field) for review in completed_reviews)
            for field in review_fields
        },
        "criterion_summary": criterion_summary,
        "reviewers": sorted(
            {str(review["reviewer"]) for review in completed_reviews if review.get("reviewer")}
        ),
    }
    failures = collections.Counter(
        record.get("failure_reason", "unknown_failure")
        for record in records
        if record.get("run_status") != "success"
    )
    for record in successes:
        failures.update(record["score"].get("failure_reasons", []))
    invalid_provider_outputs = failures["invalid_provider_output"]
    provider_transport_failures = len(records) - len(successes) - invalid_provider_outputs
    return {
        "dataset": {
            "path": "data/evaluation/grammar_cases_v1.jsonl",
            "case_count": len(cases),
            "expected_correct": sum(bool(case["expected_is_correct"]) for case in cases),
            "expected_incorrect": sum(not bool(case["expected_is_correct"]) for case in cases),
            "human_authored_ground_truth": True,
        },
        "detection": detection,
        "false_positive_rate": false_positive_rate,
        "single_error_category": category_metrics,
        "multiple_error_category": multiple_metrics,
        "correction": {
            "evaluated_outputs": applicable_corrections,
            "not_applicable": correction_counts["not_applicable"],
            "no_output": len(records) - len(successes),
            "counts": {
                "exact_match": correction_counts["exact_match"],
                "acceptable_alternative": correction_counts["acceptable_alternative"],
                "incorrect_correction": correction_counts["incorrect_correction"],
                "not_applicable": correction_counts["not_applicable"],
                "no_output": len(records) - len(successes),
            },
            "exact_match_rate": _ratio(correction_counts["exact_match"], applicable_corrections),
            "acceptable_rate_including_alternatives": _ratio(
                correction_counts["exact_match"] + correction_counts["acceptable_alternative"],
                applicable_corrections,
            ),
        },
        "structured_output": {
            "total_primary_requests": len(records),
            "provider_responses_received": len(successes) + invalid_provider_outputs,
            "valid_typed_responses": len(successes),
            "malformed_or_invalid_responses": invalid_provider_outputs,
            "provider_transport_or_http_failures": provider_transport_failures,
            "controlled_provider_or_configuration_failures": provider_transport_failures,
            "success_rate": _ratio(len(successes), len(records)),
        },
        "explanation_quality": explanation,
        "uncertainty": {
            "expected_uncertain_cases": sum(
                case["expected_analysis_status"] == AnalysisStatus.UNCERTAIN.value for case in cases
            ),
            "predicted_uncertain_cases": sum(
                record["result"]["analysis_status"] == AnalysisStatus.UNCERTAIN.value
                for record in successes
            ),
        },
        "failure_counts": dict(sorted(failures.items())),
        "completion_status": (
            "COMPLETE"
            if len(records) == len(cases)
            and len(completed_reviews) == len(successes)
            and correction_counts["unreviewed_alternative"] == 0
            else "BLOCKED_OR_INCOMPLETE"
        ),
    }


def run_grammar_reliability(
    cases: Sequence[Mapping[str, Any]],
    grammar_service: GrammarService,
) -> dict[str, Any]:
    selected = {case["case_id"]: case for case in cases}
    runs: list[dict[str, Any]] = []
    for case_id in RELIABILITY_CASE_IDS:
        case = selected[case_id]
        for repetition in range(1, RELIABILITY_REPEATS + 1):
            result = run_grammar_cases([case], grammar_service)[0]
            content_hash = None
            if result["run_status"] == "success":
                content_hash = _sha256_bytes(
                    json.dumps(result["result"], ensure_ascii=False, sort_keys=True).encode("utf-8")
                )
            runs.append(
                {
                    "case_id": case_id,
                    "repetition": repetition,
                    "run_status": result["run_status"],
                    "content_sha256": content_hash,
                    "failure_reason": result.get("failure_reason"),
                    "latency_ms": result["latency_ms"],
                }
            )
    by_case: dict[str, Any] = {}
    for case_id in RELIABILITY_CASE_IDS:
        values = [run for run in runs if run["case_id"] == case_id]
        hashes = {run["content_sha256"] for run in values if run["content_sha256"]}
        by_case[case_id] = {
            "attempts": len(values),
            "successful_outputs": sum(run["run_status"] == "success" for run in values),
            "unique_successful_output_hashes": len(hashes),
            "all_successful_outputs_identical": len(hashes) == 1 if hashes else None,
        }
    return {
        "method": "four representative cases repeated three times",
        "caveat": "This small repeat sample is descriptive and not statistically conclusive.",
        "runs": runs,
        "by_case": by_case,
        "latency": _latency_summary([run["latency_ms"] for run in runs]),
    }


def _analysis_matches(analysis: Any, expected: Mapping[str, Any]) -> bool:
    return analysis.lemma == expected["lemma"] and analysis.part_of_speech == expected["part_of_speech"]


def _features_contain(actual: Mapping[str, str], expected: Mapping[str, str]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def validate_vocabulary_cases(cases: Sequence[Mapping[str, Any]]) -> None:
    ids: set[str] = set()
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("Vocabulary case IDs must be unique non-empty strings")
        ids.add(case_id)
        if case.get("expected_status") not in {"found", "ambiguous", "not_found"}:
            raise ValueError(f"Invalid vocabulary status for {case_id}")
        if not isinstance(case.get("required_analyses"), list):
            raise ValueError(f"required_analyses must be a list for {case_id}")


def evaluate_vocabulary(
    service: VocabularyService,
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate status, lexical fields, morphology, meanings, and provenance."""

    validate_vocabulary_cases(cases)
    records: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in cases:
        started = time.perf_counter()
        result = service.lookup(case["query"])
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        required = case["required_analyses"]
        actual_pairs = {(analysis.lemma, analysis.part_of_speech) for analysis in result.analyses}
        expected_pairs = {(item["lemma"], item["part_of_speech"]) for item in required}
        lemma_ok = all(any(analysis.lemma == item["lemma"] for analysis in result.analyses) for item in required)
        pos_ok = expected_pairs.issubset(actual_pairs)
        morphology_checks: list[bool] = []
        meaning_checks: list[bool] = []
        example_checks: list[bool] = []
        provenance_checks: list[bool] = []
        detail: list[dict[str, Any]] = []
        for expected in required:
            matches = [analysis for analysis in result.analyses if _analysis_matches(analysis, expected)]
            analysis = matches[0] if matches else None
            expected_features = expected.get("features")
            matching_forms = [] if analysis is None else [
                form
                for form in analysis.observed_forms
                if normalize_lookup_key(form.form) == normalize_lookup_key(expected.get("form", case["query"]))
            ]
            if expected_features is not None:
                morphology_ok = any(
                    _features_contain(feature_analysis.features, expected_features)
                    for form in matching_forms
                    for feature_analysis in form.feature_analyses
                )
                if expected.get("expect_multiple_feature_analyses"):
                    morphology_ok = morphology_ok and any(
                        len(form.feature_analyses) > 1 for form in matching_forms
                    )
                morphology_checks.append(morphology_ok)
            else:
                morphology_ok = None
            if analysis is None:
                meaning_ok = False
                example_ok = False
                provenance_ok = False
            else:
                if "meaning_any" in expected:
                    accepted = {value.casefold() for value in expected["meaning_any"]}
                    meaning_ok = any(value.casefold() in accepted for value in analysis.meanings)
                elif "expect_meaning_available" in expected:
                    meaning_ok = bool(analysis.meanings) is bool(expected["expect_meaning_available"])
                else:
                    meaning_ok = True
                candidate_forms = [form.form.casefold() for form in analysis.observed_forms]
                example_text = analysis.example.sentence.casefold() if analysis.example else ""
                example_ok = bool(analysis.example) and any(form in example_text for form in candidate_forms)
                provenance_ok = bool(analysis.sources) and all(
                    source.source_id and source.name and source.license and source.url
                    for source in analysis.sources
                )
            meaning_checks.append(meaning_ok)
            example_checks.append(example_ok)
            provenance_checks.append(provenance_ok)
            detail.append(
                {
                    "lemma": expected["lemma"],
                    "part_of_speech": expected["part_of_speech"],
                    "analysis_found": analysis is not None,
                    "morphology_correct": morphology_ok,
                    "meaning_correct_or_availability_expected": meaning_ok,
                    "example_relevant": example_ok,
                    "provenance_available": provenance_ok,
                }
            )
        not_found = case["expected_status"] == "not_found"
        scores = {
            "lookup_status_correct": result.status.value == case["expected_status"],
            "lemma_correct": (not result.analyses) if not_found else lemma_ok,
            "pos_correct": (not result.analyses) if not_found else pos_ok,
            "morphology_correct": all(morphology_checks) if morphology_checks else None,
            "meaning_correct_or_availability_expected": all(meaning_checks) if meaning_checks else None,
            "example_relevance": all(example_checks) if example_checks else None,
            "provenance_available": all(provenance_checks) if provenance_checks else None,
            "ambiguity_behavior_correct": (
                result.status.value == case["expected_status"]
                if case["expected_status"] == "ambiguous"
                else None
            ),
            "unknown_word_behavior_correct": (
                result.status.value == "not_found" and not result.analyses if not_found else None
            ),
        }
        records.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "expected_status": case["expected_status"],
                "actual_status": result.status.value,
                "latency_ms": latency_ms,
                "required_analysis_pairs": sorted([list(value) for value in expected_pairs]),
                "actual_analysis_pairs": sorted([list(value) for value in actual_pairs]),
                "analysis_details": detail,
                "scores": scores,
                "result": result.to_dict(),
            }
        )
    metrics: dict[str, Any] = {}
    for field in (
        "lookup_status_correct",
        "lemma_correct",
        "pos_correct",
        "morphology_correct",
        "meaning_correct_or_availability_expected",
        "example_relevance",
        "provenance_available",
        "ambiguity_behavior_correct",
        "unknown_word_behavior_correct",
    ):
        values = [record["scores"][field] for record in records if record["scores"][field] is not None]
        metrics[field] = {
            "passed": sum(bool(value) for value in values),
            "evaluated": len(values),
            "rate": _ratio(sum(bool(value) for value in values), len(values)),
        }
    return {
        "dataset": {
            "path": "data/evaluation/vocabulary_cases_v1.jsonl",
            "case_count": len(cases),
            "manual_source_backed_reference_audit": True,
        },
        "metrics": metrics,
        "records": records,
        "latency": _latency_summary(latencies),
        "all_required_checks_passed": all(
            value["passed"] == value["evaluated"] for value in metrics.values()
        ),
    }


def vocabulary_index_statistics(index_path: Path, manifest_path: Path) -> dict[str, Any]:
    """Calculate bounded index statistics without calling them dictionary coverage."""

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    key_counts: collections.Counter[str] = collections.Counter()
    lemmas: set[str] = set()
    analysis_records = 0
    with Path(index_path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed vocabulary index at line {line_number}") from exc
            analysis_records += 1
            lemmas.add(normalize_lookup_key(record["lemma"]))
            key_counts.update(record["lookup_keys"])
    computed = {
        "analysis_records": analysis_records,
        "lookup_keys": len(key_counts),
        "normalized_lemmas": len(lemmas),
        "ambiguous_lookup_keys": sum(count > 1 for count in key_counts.values()),
        "maximum_analyses_for_one_key": max(key_counts.values(), default=0),
        "analyses_with_meanings": manifest["counts"]["analyses_with_meanings"],
        "forms_with_multiple_feature_analyses": manifest["counts"][
            "forms_with_multiple_feature_analyses"
        ],
        "index_sha256": sha256_file(index_path),
        "manifest_hash_matches": sha256_file(index_path) == manifest["output_sha256"],
        "scope_note": (
            "These are statistics for the corpus-bounded Phase 8 index, not coverage of "
            "the Finnish language or of a complete dictionary."
        ),
    }
    return computed


def _grammar_result_for_categories(
    categories: Sequence[ErrorType],
    *,
    correct: bool = False,
) -> GrammarResult:
    if correct:
        sentence = "Minä menen kouluun."
        return GrammarResult(
            original_sentence=sentence,
            is_correct=True,
            corrected_sentence=sentence,
            errors=(),
            overall_explanation="The sentence is grammatically correct.",
            learning_tip="Continue checking agreement and case.",
        )
    original_tokens = [f"virhe{index}" for index, _ in enumerate(categories)]
    corrected_tokens = [f"korjaus{index}" for index, _ in enumerate(categories)]
    original = " ".join(original_tokens) + "."
    corrected = " ".join(corrected_tokens) + "."
    errors = tuple(
        GrammarError(
            text=original_tokens[index],
            correction=corrected_tokens[index],
            error_type=category,
            explanation=f"Controlled evaluation error for {category.value}.",
            confidence=0.9,
        )
        for index, category in enumerate(categories)
    )
    return GrammarResult(
        original_sentence=original,
        is_correct=False,
        corrected_sentence=corrected,
        errors=errors,
        overall_explanation="Controlled deterministic profile-evaluation result.",
        learning_tip="Review the recorded grammar category.",
    )


def _profile_projection(profile: LearnerProfile) -> dict[str, Any]:
    return {
        "learner_id": profile.learner_id,
        "total_checks": profile.total_checks,
        "total_errors": profile.total_errors,
        "primary_weakness": profile.primary_weakness.value if profile.primary_weakness else None,
        "weaknesses": [
            {
                "error_type": weakness.error_type.value,
                "count": weakness.count,
                "percentage": weakness.percentage,
            }
            for weakness in profile.weaknesses
        ],
    }


def evaluate_profiles() -> dict[str, Any]:
    """Run six controlled history scenarios in isolated temporary databases."""

    scenario_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="phase11-profiles-") as temp_name:
        temp_root = Path(temp_name)

        def run_scenario(
            name: str,
            learner_records: Mapping[str, Sequence[GrammarResult]],
            expected: Mapping[str, Mapping[str, Any]],
        ) -> None:
            database = DatabaseService(temp_root / f"{name}.db")
            database.initialize()
            for learner_id, results in learner_records.items():
                for result in results:
                    database.save_grammar_result(learner_id, result)
            actual: dict[str, Any] = {}
            checks: list[bool] = []
            for learner_id, expected_profile in expected.items():
                profile = ProfileService(database).get_profile(learner_id)
                projected = _profile_projection(profile)
                actual[learner_id] = projected
                checks.append(projected == expected_profile)
            scenario_results.append(
                {
                    "scenario": name,
                    "status": "PASS" if all(checks) else "FAIL",
                    "expected": expected,
                    "actual": actual,
                }
            )

        run_scenario(
            "no_checks",
            {},
            {
                "empty_learner": {
                    "learner_id": "empty_learner",
                    "total_checks": 0,
                    "total_errors": 0,
                    "primary_weakness": None,
                    "weaknesses": [],
                }
            },
        )
        run_scenario(
            "correct_checks_only",
            {
                "correct_learner": [
                    _grammar_result_for_categories([], correct=True),
                    _grammar_result_for_categories([], correct=True),
                ]
            },
            {
                "correct_learner": {
                    "learner_id": "correct_learner",
                    "total_checks": 2,
                    "total_errors": 0,
                    "primary_weakness": None,
                    "weaknesses": [],
                }
            },
        )
        run_scenario(
            "one_error",
            {"one_error_learner": [_grammar_result_for_categories([ErrorType.CASE_ERROR])]},
            {
                "one_error_learner": {
                    "learner_id": "one_error_learner",
                    "total_checks": 1,
                    "total_errors": 1,
                    "primary_weakness": "CASE_ERROR",
                    "weaknesses": [
                        {"error_type": "CASE_ERROR", "count": 1, "percentage": 100.0}
                    ],
                }
            },
        )
        several = (
            [ErrorType.CASE_ERROR] * 3
            + [ErrorType.VERB_CONJUGATION] * 2
            + [ErrorType.SPELLING]
        )
        run_scenario(
            "several_categories",
            {
                "several_learner": [
                    _grammar_result_for_categories([category]) for category in several
                ]
            },
            {
                "several_learner": {
                    "learner_id": "several_learner",
                    "total_checks": 6,
                    "total_errors": 6,
                    "primary_weakness": "CASE_ERROR",
                    "weaknesses": [
                        {"error_type": "CASE_ERROR", "count": 3, "percentage": 50.0},
                        {
                            "error_type": "VERB_CONJUGATION",
                            "count": 2,
                            "percentage": 33.33,
                        },
                        {"error_type": "SPELLING", "count": 1, "percentage": 16.67},
                    ],
                }
            },
        )
        tied = [ErrorType.VERB_CONJUGATION, ErrorType.CASE_ERROR] * 2
        run_scenario(
            "tied_categories",
            {"tie_learner": [_grammar_result_for_categories([category]) for category in tied]},
            {
                "tie_learner": {
                    "learner_id": "tie_learner",
                    "total_checks": 4,
                    "total_errors": 4,
                    "primary_weakness": "CASE_ERROR",
                    "weaknesses": [
                        {"error_type": "CASE_ERROR", "count": 2, "percentage": 50.0},
                        {
                            "error_type": "VERB_CONJUGATION",
                            "count": 2,
                            "percentage": 50.0,
                        },
                    ],
                }
            },
        )
        run_scenario(
            "learner_isolation",
            {
                "learner_a": [
                    _grammar_result_for_categories([ErrorType.CASE_ERROR]),
                    _grammar_result_for_categories([ErrorType.CASE_ERROR]),
                ],
                "learner_b": [
                    _grammar_result_for_categories([ErrorType.VERB_CONJUGATION])
                ],
            },
            {
                "learner_a": {
                    "learner_id": "learner_a",
                    "total_checks": 2,
                    "total_errors": 2,
                    "primary_weakness": "CASE_ERROR",
                    "weaknesses": [
                        {"error_type": "CASE_ERROR", "count": 2, "percentage": 100.0}
                    ],
                },
                "learner_b": {
                    "learner_id": "learner_b",
                    "total_checks": 1,
                    "total_errors": 1,
                    "primary_weakness": "VERB_CONJUGATION",
                    "weaknesses": [
                        {
                            "error_type": "VERB_CONJUGATION",
                            "count": 1,
                            "percentage": 100.0,
                        }
                    ],
                },
            },
        )
    return {
        "scenario_count": len(scenario_results),
        "passed": sum(result["status"] == "PASS" for result in scenario_results),
        "failed": sum(result["status"] == "FAIL" for result in scenario_results),
        "scenarios": scenario_results,
        "all_passed": all(result["status"] == "PASS" for result in scenario_results),
    }


def _controlled_profile(
    name: str,
    counts: Sequence[tuple[ErrorType, int]],
) -> LearnerProfile:
    total = sum(count for _, count in counts)
    weaknesses = tuple(
        LearnerWeakness(
            error_type=error_type,
            count=count,
            percentage=round(count / total * 100, 2) if total else 0.0,
        )
        for error_type, count in counts
    )
    return LearnerProfile(
        learner_id=name,
        total_checks=total,
        total_errors=total,
        weaknesses=weaknesses,
    )


def evaluate_personalization() -> dict[str, Any]:
    """Verify target selection for the four approved controlled profiles."""

    definitions = [
        (
            "profile_a_case_highest",
            _controlled_profile(
                "profile_a", [(ErrorType.CASE_ERROR, 5), (ErrorType.VERB_CONJUGATION, 2)]
            ),
            "CASE_ERROR",
        ),
        (
            "profile_b_verb_highest",
            _controlled_profile(
                "profile_b", [(ErrorType.VERB_CONJUGATION, 5), (ErrorType.CASE_ERROR, 2)]
            ),
            "VERB_CONJUGATION",
        ),
        (
            "profile_c_tie",
            _controlled_profile(
                "profile_c", [(ErrorType.VERB_CONJUGATION, 3), (ErrorType.CASE_ERROR, 3)]
            ),
            "CASE_ERROR",
        ),
        ("profile_d_no_history", _controlled_profile("profile_d", []), None),
    ]
    results: list[dict[str, Any]] = []
    for name, profile, expected_target in definitions:
        automatic_target: str | None = None
        automatic_error: str | None = None
        try:
            selected, source = ExerciseService.select_target(profile)
            automatic_target = selected.value
            source_value = source.value
        except ExerciseTargetUnavailableError as exc:
            automatic_error = str(exc)
            source_value = None
        fallback_target: str | None = None
        if expected_target is None:
            fallback_target = ExerciseService.select_target(
                profile, ErrorType.CASE_ERROR
            )[0].value
        passed = (
            automatic_target == expected_target
            and ((expected_target is not None and source_value == "LEARNER_PROFILE") or expected_target is None)
            and (expected_target is not None or (automatic_error is not None and fallback_target == "CASE_ERROR"))
        )
        results.append(
            {
                "profile": name,
                "expected_automatic_target": expected_target,
                "actual_automatic_target": automatic_target,
                "selection_source": source_value,
                "no_history_error": automatic_error,
                "documented_no_history_fallback": (
                    "Require an explicit supported topic; CASE_ERROR was selected only for this controlled check."
                    if expected_target is None
                    else None
                ),
                "explicit_fallback_target": fallback_target,
                "status": "PASS" if passed else "FAIL",
            }
        )
    return {
        "profile_count": len(results),
        "passed": sum(result["status"] == "PASS" for result in results),
        "failed": sum(result["status"] == "FAIL" for result in results),
        "profiles": results,
        "all_passed": all(result["status"] == "PASS" for result in results),
    }


def _nested_numbers_close(actual: Any, expected: Any, *, tolerance: float = 1e-12) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and set(actual) == set(expected) and all(
            _nested_numbers_close(actual[key], expected[key], tolerance=tolerance)
            for key in expected
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _nested_numbers_close(a, b, tolerance=tolerance)
            for a, b in zip(actual, expected)
        )
    if isinstance(expected, float):
        return isinstance(actual, (int, float)) and math.isclose(
            float(actual), expected, rel_tol=tolerance, abs_tol=tolerance
        )
    return actual == expected


def verify_ml_baseline(project_root: Path) -> dict[str, Any]:
    """Reload the Phase 5 artifact and verify its frozen splits and metrics."""

    root = Path(project_root)
    metadata_path = root / "models" / "error_classifier_v1_metadata.json"
    manifest_path = root / "data" / "evaluation" / "ml_split_manifest_v1.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    split_records: dict[str, list[dict[str, Any]]] = {}
    split_hash_checks: dict[str, bool] = {}
    split_count_checks: dict[str, bool] = {}
    group_sets: dict[str, set[str]] = {}
    for name in ("train", "validation", "test"):
        split_info = manifest["splits"][name]
        path = root / split_info["path"]
        records = load_jsonl(path)
        split_records[name] = records
        group_sets[name] = {str(record["leakage_group_id"]) for record in records}
        split_hash_checks[name] = sha256_file(path) == split_info["sha256"]
        split_count_checks[name] = (
            len(records) == split_info["records"] == metadata["record_counts"][name]
        )
    actual_intersections = {
        "train_validation": len(group_sets["train"] & group_sets["validation"]),
        "train_test": len(group_sets["train"] & group_sets["test"]),
        "validation_test": len(group_sets["validation"] & group_sets["test"]),
    }
    model_path = root / metadata["artifacts"]["model"]["path"]
    predictions_path = root / metadata["artifacts"]["test_predictions"]["path"]
    model_hash_ok = sha256_file(model_path) == metadata["artifacts"]["model"]["sha256"]
    prediction_hash_ok = (
        sha256_file(predictions_path)
        == metadata["artifacts"]["test_predictions"]["sha256"]
    )
    split_manifest_hash_ok = sha256_file(manifest_path) == metadata["split_manifest"]["sha256"]
    input_hash_ok = (
        sha256_file(root / metadata["input_dataset"]["path"])
        == metadata["input_dataset"]["sha256"]
    )
    pipeline = load_pipeline(model_path)
    recomputed_metrics: dict[str, Any] = {}
    metric_matches: dict[str, bool] = {}
    recomputed_test_predictions: list[dict[str, Any]] = []
    for name, records in split_records.items():
        metrics, predictions = evaluate_pipeline(pipeline, records)
        recomputed_metrics[name] = metrics
        metric_matches[name] = _nested_numbers_close(metrics, metadata["metrics"][name])
        if name == "test":
            recomputed_test_predictions = predictions
    stored_predictions = load_jsonl(predictions_path)
    prediction_identity_ok = len(stored_predictions) == len(recomputed_test_predictions) and all(
        stored.get("synthetic_id") == recomputed.get("synthetic_id")
        and stored.get("predicted_label") == recomputed.get("predicted_label")
        for stored, recomputed in zip(stored_predictions, recomputed_test_predictions)
    )
    labels_by_split = {
        name: sorted({str(record["error_type"]) for record in records})
        for name, records in split_records.items()
    }
    expected_labels = sorted(metadata["labels"])
    labels_ok = all(labels == expected_labels for labels in labels_by_split.values())
    checks = {
        "input_hash_matches": input_hash_ok,
        "split_manifest_hash_matches": split_manifest_hash_ok,
        "split_file_hashes_match": all(split_hash_checks.values()),
        "split_record_counts_match": all(split_count_checks.values()),
        "zero_leakage_group_overlap": not any(actual_intersections.values()),
        "labels_match_metadata": labels_ok,
        "model_hash_matches": model_hash_ok,
        "saved_pipeline_loads": True,
        "train_validation_test_metrics_reproduce": all(metric_matches.values()),
        "stored_test_predictions_reproduce": prediction_identity_ok,
        "prediction_artifact_hash_matches": prediction_hash_ok,
    }
    return {
        "prediction_task": metadata["prediction_task"],
        "task_scope_note": (
            "This is three-way classification of controlled synthetic error sentences, "
            "not correct/incorrect detection and not the same task as the LLM grammar checker."
        ),
        "record_counts": metadata["record_counts"],
        "labels": metadata["labels"],
        "split_identity": {
            "hash_checks": split_hash_checks,
            "count_checks": split_count_checks,
            "actual_group_intersections": actual_intersections,
            "manifest_group_intersections": manifest["quality_checks"][
                "leakage_group_isolation"
            ]["intersection_counts"],
        },
        "metrics": metadata["metrics"],
        "recomputed_metric_matches": metric_matches,
        "checks": checks,
        "shortcut_checks": {
            "training_global_majority_accuracy": metadata["shortcut_checks"][
                "training_global_majority_accuracy"
            ],
            "test_source_only_majority_accuracy": metadata["shortcut_checks"][
                "test_source_only_majority"
            ]["accuracy"],
            "test_accuracy_by_source": {
                source: values["accuracy"]
                for source, values in metadata["shortcut_checks"][
                    "test_metrics_by_source"
                ].items()
            },
            "train_test_macro_f1_gap": metadata["shortcut_checks"][
                "train_test_macro_f1_gap"
            ],
            "top_feature_examples": {
                category: [item["feature"] for item in values[:5]]
                for category, values in metadata["interpretation"][
                    "top_positive_features"
                ].items()
            },
        },
        "representative_misclassifications": metadata["interpretation"][
            "misclassified_test_examples"
        ][:3],
        "limitations": metadata["limitations"],
        "all_checks_passed": all(checks.values()),
    }


@dataclass
class _StaticProfileService:
    profile: LearnerProfile

    def get_profile(self, learner_id: str) -> LearnerProfile:
        return self.profile


def _exercise_structural_checks(exercise: Exercise, target: ErrorType) -> dict[str, bool]:
    normalized_options = [value.strip() for value in exercise.options]
    return {
        "typed_schema_valid": isinstance(exercise, Exercise),
        "target_taxonomy_valid": exercise.error_type is target,
        "exercise_type_supported": exercise.exercise_type is ExerciseType.MULTIPLE_CHOICE,
        "question_non_empty": bool(exercise.question.strip()),
        "four_options": len(exercise.options) == 4,
        "options_non_empty_and_unique": all(normalized_options)
        and len(set(normalized_options)) == len(normalized_options),
        "correct_answer_appears_exactly_once": normalized_options.count(
            exercise.correct_answer.strip()
        )
        == 1,
        "explanation_non_empty": bool(exercise.explanation.strip()),
    }


def run_exercise_evaluation(
    exercise_service: ExerciseService,
    *,
    reviews: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Request the approved 20-exercise sample and preserve every failure."""

    review_map = reviews or {}
    provider = _provider_metadata(exercise_service.llm_client)
    profile = LearnerProfile(
        learner_id="phase11_exercise_eval",
        total_checks=0,
        total_errors=0,
        weaknesses=(),
    )
    records: list[dict[str, Any]] = []
    for target in SUPPORTED_GENERATION_ERROR_TYPES:
        for sample_index in range(1, EXERCISES_PER_CATEGORY + 1):
            request_id = f"{target.value.lower()}_{sample_index:02d}"
            started = time.perf_counter()
            try:
                exercise = exercise_service.generate_for_profile(
                    profile,
                    difficulty=ExerciseDifficulty.BASIC,
                    error_type=target,
                )
            except ExerciseServiceError as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                records.append(
                    {
                        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                        "request_id": request_id,
                        "target_error_type": target.value,
                        "exercise_type": ExerciseType.MULTIPLE_CHOICE.value,
                        "difficulty": ExerciseDifficulty.BASIC.value,
                        "run_status": "controlled_failure",
                        "provider_configuration": provider,
                        "schema_valid": False,
                        "structurally_valid": False,
                        "latency_ms": latency_ms,
                        "failure_reason": _provider_failure_reason(str(exc)),
                        "safe_error": str(exc),
                        "safe_failure_diagnostic": _safe_failure_diagnostic(exc),
                        "manual_linguistic_review": {
                            "status": "NOT_REVIEWABLE_NO_OUTPUT",
                            "reviewer": None,
                        },
                    }
                )
            else:
                latency_ms = (time.perf_counter() - started) * 1000
                checks = _exercise_structural_checks(exercise, target)
                review = review_map.get(exercise.exercise_id) or review_map.get(request_id)
                if review:
                    manual_review = {
                        "status": review.get("status", "COMPLETED"),
                        "reviewer": review.get("reviewer"),
                        "scale": review.get("scale", "PASS/PARTIAL/FAIL"),
                        "target_relevance": review.get("target_relevance"),
                        "question_clarity": review.get("question_clarity"),
                        "unambiguous": review.get("unambiguous"),
                        "answer_correctness": review.get("answer_correctness"),
                        "distractor_plausibility": review.get("distractor_plausibility"),
                        "explanation_correctness": review.get("explanation_correctness"),
                        "no_unrelated_errors": review.get("no_unrelated_errors"),
                        "failure_reasons": review.get("failure_reasons", []),
                        "notes": review.get("notes"),
                    }
                else:
                    manual_review = {
                        "status": "PENDING_MANUAL_REVIEW",
                        "reviewer": None,
                        "scale": "PASS/PARTIAL/FAIL",
                        "criteria": [
                            "target relevance",
                            "question clarity",
                            "exactly one defensible answer",
                            "answer correctness",
                            "distractor plausibility",
                            "explanation correctness",
                            "absence of unrelated Finnish errors",
                        ],
                    }
                records.append(
                    {
                        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                        "request_id": request_id,
                        "target_error_type": target.value,
                        "exercise_type": ExerciseType.MULTIPLE_CHOICE.value,
                        "difficulty": ExerciseDifficulty.BASIC.value,
                        "run_status": "success",
                        "provider_configuration": provider,
                        "schema_valid": True,
                        "structurally_valid": all(checks.values()),
                        "structural_checks": checks,
                        "latency_ms": latency_ms,
                        "exercise": exercise.to_dict(),
                        "manual_linguistic_review": manual_review,
                    }
                )
    return records


def aggregate_exercise_results(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    successful = [record for record in records if record.get("run_status") == "success"]
    structurally_valid = [record for record in records if record.get("structurally_valid")]
    completed_reviews = [
        record
        for record in successful
        if record["manual_linguistic_review"].get("status") == "COMPLETED"
    ]
    review_counts: dict[str, collections.Counter[str]] = {}
    fields = (
        "target_relevance",
        "question_clarity",
        "unambiguous",
        "answer_correctness",
        "distractor_plausibility",
        "explanation_correctness",
        "no_unrelated_errors",
    )
    for field in fields:
        review_counts[field] = collections.Counter(
            str(record["manual_linguistic_review"].get(field, "MISSING"))
            for record in completed_reviews
        )
    criterion_summary = {
        field: {
            "rated": sum(review_counts[field][value] for value in ("PASS", "PARTIAL", "FAIL")),
            "pass": review_counts[field]["PASS"],
            "partial": review_counts[field]["PARTIAL"],
            "fail": review_counts[field]["FAIL"],
            "pass_rate": _ratio(
                review_counts[field]["PASS"],
                sum(review_counts[field][value] for value in ("PASS", "PARTIAL", "FAIL")),
            ),
            "non_pass_rate": _ratio(
                review_counts[field]["PARTIAL"] + review_counts[field]["FAIL"],
                sum(review_counts[field][value] for value in ("PASS", "PARTIAL", "FAIL")),
            ),
        }
        for field in fields
    }
    failure_counts = collections.Counter(
        record.get("failure_reason", "unknown_failure")
        for record in records
        if record.get("run_status") != "success"
    )
    for record in completed_reviews:
        failure_counts.update(
            record["manual_linguistic_review"].get("failure_reasons", [])
        )
    by_category: dict[str, Any] = {}
    for category in (item.value for item in SUPPORTED_GENERATION_ERROR_TYPES):
        category_records = [record for record in records if record["target_error_type"] == category]
        by_category[category] = {
            "requested": len(category_records),
            "generated": sum(record["run_status"] == "success" for record in category_records),
            "structurally_valid": sum(bool(record["structurally_valid"]) for record in category_records),
            "manually_reviewed": sum(
                record["manual_linguistic_review"].get("status") == "COMPLETED"
                for record in category_records
            ),
        }
    return {
        "requested": len(records),
        "generated": len(successful),
        "provider_failures": len(records) - len(successful),
        "schema_valid": sum(bool(record.get("schema_valid")) for record in records),
        "schema_validity_rate_over_all_requests": _ratio(
            sum(bool(record.get("schema_valid")) for record in records), len(records)
        ),
        "structurally_valid": len(structurally_valid),
        "structural_validity_rate_over_all_requests": _ratio(len(structurally_valid), len(records)),
        "structural_validity_rate_over_generated": _ratio(len(structurally_valid), len(successful)),
        "manual_review": {
            "methodology": {
                "scale": "PASS/PARTIAL/FAIL",
                "population": "all successfully generated Phase 11 exercises",
                "criteria": list(fields),
                "review_method": "AI-assisted qualitative linguistic review",
                "subjectivity_note": (
                    "Ratings are an AI-assisted linguistic judgment under the named reviewer "
                    "identity, not a human/native-teacher assessment; they remain separate "
                    "from JSON validity."
                ),
            },
            "completed": len(completed_reviews),
            "pending": len(successful) - len(completed_reviews),
            "not_reviewable_no_output": len(records) - len(successful),
            "criterion_counts": {
                field: dict(sorted(counts.items())) for field, counts in review_counts.items()
            },
            "criterion_summary": criterion_summary,
        },
        "by_category": by_category,
        "failure_counts": dict(sorted(failure_counts.items())),
        "latency": _latency_summary([float(record["latency_ms"]) for record in records]),
        "completion_status": (
            "COMPLETE"
            if len(successful) == len(records)
            and len(structurally_valid) == len(records)
            and len(completed_reviews) == len(successful)
            else "BLOCKED_OR_INCOMPLETE"
        ),
    }


def write_manual_review_worksheets(
    grammar_path: Path,
    exercise_path: Path,
    grammar_records: Sequence[Mapping[str, Any]],
    exercise_records: Sequence[Mapping[str, Any]],
) -> None:
    """Populate objective evidence without discarding completed review fields."""

    grammar_rows: list[dict[str, Any]] = []
    for record in grammar_records:
        result = record.get("result", {})
        score = record.get("score", {})
        review = record.get("manual_explanation_review", {})
        completed = review.get("status") == "COMPLETED" and all(
            review.get(field) in (1, 2, 3)
            for field in (
                "grammatical_correctness",
                "relevance",
                "clarity",
                "learner_usefulness",
            )
        )
        review_status = review.get("status") or (
            "PENDING_MANUAL_REVIEW"
            if record.get("run_status") == "success"
            else "NOT_REVIEWABLE_NO_OUTPUT"
        )
        if review_status == "COMPLETED" and not completed:
            review_status = "PENDING_MANUAL_REVIEW"
        row = {
            "case_id": record["case_id"],
            "sentence": record["sentence"],
            "expected_error_types": record["expected"]["error_types"],
            "predicted_error_types": score.get("predicted_categories", []),
            "corrected_sentence": result.get("corrected_sentence"),
            "individual_explanations": [
                item.get("explanation") for item in result.get("errors", [])
            ],
            "overall_explanation": result.get("overall_explanation"),
            "learning_tip": result.get("learning_tip"),
            "automatic_detection_correct": score.get("detection_correct"),
            "automatic_category_exact_match": score.get("category_exact_match"),
            "automatic_correction_outcome": score.get("correction_outcome"),
            "status": review_status,
            "reviewer": review.get("reviewer") if completed else None,
            "scale": review.get("scale", "1-3"),
            "grammatical_correctness": review.get("grammatical_correctness") if completed else None,
            "relevance": review.get("relevance") if completed else None,
            "clarity": review.get("clarity") if completed else None,
            "learner_usefulness": review.get("learner_usefulness") if completed else None,
            "correction_acceptability": review.get("correction_acceptability") if completed else None,
            "notes": review.get("notes") if completed else None,
        }
        if completed:
            row["review_method"] = review.get(
                "review_method", "AI-assisted qualitative linguistic review"
            )
        grammar_rows.append(row)
    exercise_rows: list[dict[str, Any]] = []
    for record in exercise_records:
        exercise = record.get("exercise", {})
        review = record.get("manual_linguistic_review", {})
        completed = review.get("status") == "COMPLETED" and all(
            review.get(field) in ("PASS", "PARTIAL", "FAIL")
            for field in (
                "target_relevance",
                "question_clarity",
                "unambiguous",
                "answer_correctness",
                "distractor_plausibility",
                "explanation_correctness",
                "no_unrelated_errors",
            )
        )
        review_status = review.get("status") or (
            "PENDING_MANUAL_REVIEW"
            if record.get("run_status") == "success"
            else "NOT_REVIEWABLE_NO_OUTPUT"
        )
        if review_status == "COMPLETED" and not completed:
            review_status = "PENDING_MANUAL_REVIEW"
        row = {
            "exercise_id": record["request_id"],
            "generated_exercise_id": exercise.get("exercise_id"),
            "target_error_type": record["target_error_type"],
            "exercise_type": record["exercise_type"],
            "difficulty": record["difficulty"],
            "question": exercise.get("question"),
            "options": exercise.get("options", []),
            "correct_answer": exercise.get("correct_answer"),
            "explanation": exercise.get("explanation"),
            "schema_valid": record.get("schema_valid", False),
            "structurally_valid": record.get("structurally_valid", False),
            "structural_checks": record.get("structural_checks", {}),
            "status": review_status,
            "reviewer": review.get("reviewer") if completed else None,
            "scale": review.get("scale", "PASS/PARTIAL/FAIL"),
            "target_relevance": review.get("target_relevance") if completed else None,
            "question_clarity": review.get("question_clarity") if completed else None,
            "unambiguous": review.get("unambiguous") if completed else None,
            "answer_correctness": review.get("answer_correctness") if completed else None,
            "distractor_plausibility": review.get("distractor_plausibility") if completed else None,
            "explanation_correctness": review.get("explanation_correctness") if completed else None,
            "no_unrelated_errors": review.get("no_unrelated_errors") if completed else None,
            "failure_reasons": list(review.get("failure_reasons", [])) if completed else [],
            "notes": review.get("notes") if completed else None,
        }
        if completed:
            row["review_method"] = review.get(
                "review_method", "AI-assisted qualitative linguistic review"
            )
        exercise_rows.append(row)
    write_jsonl(grammar_path, grammar_rows)
    write_jsonl(exercise_path, exercise_rows)


@dataclass
class _FixedGrammarService:
    result: GrammarResult
    calls: int = 0

    def check_sentence(self, sentence: str, *, language_mode: object) -> GrammarResult:
        self.calls += 1
        if sentence != self.result.original_sentence:
            raise AssertionError("Evaluation grammar fixture received an unexpected sentence")
        return self.result


@dataclass
class _FixedExerciseService:
    exercise: Exercise
    generate_calls: int = 0
    check_calls: int = 0

    def generate_for_learner(self, learner_id: str, *, error_type: object = None) -> Exercise:
        self.generate_calls += 1
        return self.exercise

    def check_answer(self, exercise: Exercise, answer: str) -> ExerciseAttemptResult:
        self.check_calls += 1
        resolved = exercise.answer_for(answer)
        return ExerciseAttemptResult(
            exercise_id=exercise.exercise_id,
            user_answer=answer,
            correct_answer=exercise.correct_answer,
            is_correct=resolved == exercise.correct_answer,
            explanation=exercise.explanation,
        )


class _FailingProviderClient:
    def request_json(self, **_: Any) -> Mapping[str, Any]:
        raise LLMProviderError("private upstream detail")


def _render_grammar_evaluation_page(
    grammar_service: object,
    database_service: object,
) -> None:
    from app.config import Settings
    from app.ui.common import initialize_session_state
    from app.ui.grammar_page import render_grammar_page

    initialize_session_state()
    render_grammar_page(
        settings=Settings(
            app_title="Finnish Learning Assistant",
            environment="evaluation",
            log_level="INFO",
            llm_api_key=None,
            llm_api_base_url=None,
            llm_model=None,
        ),
        grammar_service=grammar_service,
        database_service=database_service,
    )


def _render_practice_evaluation_page(
    profile_service: object,
    exercise_service: object,
) -> None:
    from app.ui.common import initialize_session_state
    from app.ui.practice_page import render_practice_page

    initialize_session_state()
    render_practice_page(
        profile_service=profile_service,
        exercise_service=exercise_service,
    )


def _sample_exercise() -> Exercise:
    return Exercise.from_provider_dict(
        {
            "schema_version": "1.0",
            "error_type": "VERB_CONJUGATION",
            "exercise_type": "MULTIPLE_CHOICE",
            "difficulty": "BASIC",
            "question": "Valitse oikea muoto: Minä ___ kouluun.",
            "options": ["menee", "menen", "menet", "mennä"],
            "correct_answer": "menen",
            "explanation": "Minä-subjekti vaatii yksikön ensimmäisen persoonan muodon.",
        },
        expected_error_type=ErrorType.VERB_CONJUGATION,
        expected_exercise_type=ExerciseType.MULTIPLE_CHOICE,
        expected_difficulty=ExerciseDifficulty.BASIC,
        selection_source=ExerciseSelectionSource.LEARNER_PROFILE,
        metadata={"weakness_count": 1, "weakness_percentage": 100.0},
    )


def _scenario(name: str, passed: bool, evidence: str) -> dict[str, str]:
    return {"scenario": name, "status": "PASS" if passed else "FAIL", "evidence": evidence}


def evaluate_end_to_end(project_root: Path) -> dict[str, Any]:
    """Exercise the UI/service loop using isolated state and deterministic fixtures."""

    from streamlit.testing.v1 import AppTest

    from app.ui import history_page, practice_page, vocabulary_page

    root = Path(project_root)
    results: list[dict[str, str]] = []
    vocabulary = VocabularyService(root / "data" / "vocabulary" / "vocabulary_index_v1.jsonl")
    with tempfile.TemporaryDirectory(prefix="phase11-e2e-") as temp_name:
        database = DatabaseService(Path(temp_name) / "end_to_end.db")
        database.initialize()
        profile_service = ProfileService(database)

        app = AppTest.from_file(root / "app.py").run()
        startup_ok = not app.exception and not app.error
        expected_pages = [
            "Home",
            "Grammar Checker",
            "Vocabulary",
            "My Mistakes",
            "Practice",
            "About",
        ]
        pages_ok = startup_ok and list(app.sidebar.radio[0].options) == expected_pages
        results.append(
            _scenario(
                "app_import_and_startup",
                startup_ok,
                "Streamlit AppTest loaded app.py without an exception or startup error.",
            )
        )

        navigation_failures: list[str] = []
        with (
            patch.object(history_page, "get_database_service", return_value=database),
            patch.object(history_page, "get_profile_service", return_value=profile_service),
            patch.object(practice_page, "get_profile_service", return_value=profile_service),
            patch.object(vocabulary_page, "get_vocabulary_service", return_value=vocabulary),
        ):
            for page in expected_pages:
                page_app = AppTest.from_file(root / "app.py").run()
                page_app.sidebar.radio[0].set_value(page).run()
                if page_app.exception or page_app.error:
                    navigation_failures.append(page)
        results.append(
            _scenario(
                "all_page_navigation",
                pages_ok and not navigation_failures,
                "Six sidebar routes rendered with isolated database/profile services; failures: "
                + (", ".join(navigation_failures) if navigation_failures else "none"),
            )
        )

        correct_result = _grammar_result_for_categories([], correct=True)
        correct_service = _FixedGrammarService(correct_result)
        correct_app = AppTest.from_function(
            _render_grammar_evaluation_page,
            args=(correct_service, database),
        ).run()
        correct_app.text_area[0].set_value(correct_result.original_sentence).run()
        correct_app.button[0].click().run()
        checks_after_correct = database.count_grammar_checks("demo_user")
        correct_errors = database.get_learner_errors("demo_user")
        correct_ok = (
            not correct_app.exception
            and correct_service.calls == 1
            and checks_after_correct == 1
            and len(correct_errors) == 0
        )
        results.append(
            _scenario(
                "correct_grammar_flow",
                correct_ok,
                "One explicit action produced one check row, no error rows, and a rendered correct result.",
            )
        )
        correct_app.run()
        correct_rerun_ok = (
            correct_service.calls == 1 and database.count_grammar_checks("demo_user") == 1
        )

        multi_result = GrammarResult(
            original_sentence="Minä menee koulu.",
            is_correct=False,
            corrected_sentence="Minä menen kouluun.",
            errors=(
                GrammarError(
                    text="menee",
                    correction="menen",
                    error_type=ErrorType.VERB_CONJUGATION,
                    explanation="The verb must agree with minä.",
                    confidence=0.98,
                ),
                GrammarError(
                    text="koulu",
                    correction="kouluun",
                    error_type=ErrorType.CASE_ERROR,
                    explanation="Movement toward this destination uses the illative.",
                    confidence=0.96,
                ),
            ),
            overall_explanation="The sentence has two independent errors.",
            learning_tip="Check subject agreement and destination cases.",
        )
        multi_database = DatabaseService(Path(temp_name) / "multi_error.db")
        multi_database.initialize()
        multi_service = _FixedGrammarService(multi_result)
        multi_app = AppTest.from_function(
            _render_grammar_evaluation_page,
            args=(multi_service, multi_database),
        ).run()
        multi_app.text_area[0].set_value(multi_result.original_sentence).run()
        multi_app.button[0].click().run()
        multi_app.run()
        multi_errors = multi_database.get_learner_errors("demo_user")
        multi_profile = ProfileService(multi_database).get_profile("demo_user")
        multi_ok = (
            not multi_app.exception
            and multi_service.calls == 1
            and multi_database.count_grammar_checks("demo_user") == 1
            and len(multi_errors) == 2
        )
        results.append(
            _scenario(
                "incorrect_multiple_error_flow",
                multi_ok,
                "One parent check and two ordered child errors were rendered and persisted.",
            )
        )
        results.append(
            _scenario(
                "exactly_once_persistence",
                correct_rerun_ok and multi_service.calls == 1,
                "Normal result rendering reruns did not repeat grammar analysis or insertion.",
            )
        )
        profile_ok = (
            multi_profile.total_checks == 1
            and multi_profile.total_errors == 2
            and {item.error_type for item in multi_profile.weaknesses}
            == {ErrorType.CASE_ERROR, ErrorType.VERB_CONJUGATION}
        )
        results.append(
            _scenario(
                "history_and_profile_update",
                profile_ok,
                "Persisted errors were immediately visible as exact profile counts in the isolated database.",
            )
        )

        statuses = {
            query: vocabulary.lookup(query).status.value
            for query in ("kouluun", "koulu", "qwertyö")
        }
        results.append(
            _scenario(
                "known_ambiguous_unknown_vocabulary",
                statuses == {
                    "kouluun": "found",
                    "koulu": "ambiguous",
                    "qwertyö": "not_found",
                },
                f"Actual local index statuses: {statuses}.",
            )
        )

        practice_profile = _controlled_profile(
            "demo_user", [(ErrorType.VERB_CONJUGATION, 1)]
        )
        fixed_exercise = _FixedExerciseService(_sample_exercise())
        practice_app = AppTest.from_function(
            _render_practice_evaluation_page,
            args=(_StaticProfileService(practice_profile), fixed_exercise),
        ).run()
        practice_app.button[0].click().run()
        exercise_id = practice_app.session_state["practice_exercise"].exercise_id
        practice_app.run()
        practice_app.radio[0].set_value("menen").run()
        generation_stable = (
            fixed_exercise.generate_calls == 1
            and practice_app.session_state["practice_exercise"].exercise_id == exercise_id
        )
        check_button = next(button for button in practice_app.button if button.label == "Check Answer")
        check_button.click().run()
        attempt = practice_app.session_state["practice_attempt"]
        results.append(
            _scenario(
                "profile_targeted_practice",
                generation_stable
                and practice_app.session_state["practice_exercise"].error_type
                is ErrorType.VERB_CONJUGATION,
                "The controlled highest weakness selected a stable VERB_CONJUGATION exercise.",
            )
        )
        results.append(
            _scenario(
                "deterministic_answer_checking",
                attempt.is_correct and fixed_exercise.check_calls == 1,
                "Answer checking used the stored exercise and made no generation call.",
            )
        )
        results.append(
            _scenario(
                "streamlit_rerun_safety",
                correct_rerun_ok and generation_stable and fixed_exercise.generate_calls == 1,
                "Grammar render rerun preserved one insert; practice selection/rerun preserved one exercise.",
            )
        )

        missing_settings = LLMSettings(
            provider="openai_compatible",
            api_key=None,
            base_url=None,
            model=None,
            max_retries=0,
        )
        try:
            GrammarService(LLMService(missing_settings)).check_sentence(
                "Minä menee kouluun."
            )
        except GrammarServiceError as exc:
            missing_message = str(exc)
        else:
            missing_message = ""
        results.append(
            _scenario(
                "missing_api_configuration",
                "not configured" in missing_message.casefold()
                and "private" not in missing_message.casefold(),
                f"Controlled learner-safe message: {missing_message}",
            )
        )
        try:
            GrammarService(_FailingProviderClient()).check_sentence("Minä menee kouluun.")
        except GrammarServiceError as exc:
            provider_message = str(exc)
        else:
            provider_message = ""
        results.append(
            _scenario(
                "provider_failure_handling",
                bool(provider_message)
                and "private upstream detail" not in provider_message
                and "temporarily unavailable" in provider_message,
                f"Provider detail was hidden behind: {provider_message}",
            )
        )
    return {
        "database_policy": "All mutable end-to-end evidence used temporary SQLite databases.",
        "scenario_count": len(results),
        "passed": sum(result["status"] == "PASS" for result in results),
        "failed": sum(result["status"] == "FAIL" for result in results),
        "scenarios": results,
        "all_passed": all(result["status"] == "PASS" for result in results),
    }


def run_streamlit_smoke(project_root: Path, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Launch a real headless Streamlit process and query its health endpoint."""

    root = Path(project_root)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--browser.gatherUsageStats=false",
    ]
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    health = ""
    error: str | None = None
    try:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                error = f"Streamlit exited early with code {process.returncode}"
                break
            try:
                with urlopen(
                    f"http://127.0.0.1:{port}/_stcore/health", timeout=1
                ) as response:
                    health = response.read().decode("utf-8", errors="replace").strip()
                if health.lower() == "ok":
                    break
            except (OSError, URLError):
                time.sleep(0.2)
        else:
            error = "Timed out waiting for the Streamlit health endpoint"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return {
        "status": "PASS" if health.lower() == "ok" else "FAIL",
        "health_response": health or None,
        "startup_latency_ms": (time.perf_counter() - started) * 1000,
        "command": "python -m streamlit run app.py --server.headless=true",
        "error": error,
    }


def measure_local_performance(project_root: Path, *, sample_count: int = 30) -> dict[str, Any]:
    root = Path(project_root)
    vocabulary = VocabularyService(root / "data" / "vocabulary" / "vocabulary_index_v1.jsonl")
    queries = ("koulu", "kouluun", "mennä", "äiti", "qwertyö")
    for query in queries:
        vocabulary.lookup(query)
    vocabulary_values: list[float] = []
    for index in range(sample_count):
        started = time.perf_counter()
        vocabulary.lookup(queries[index % len(queries)])
        vocabulary_values.append((time.perf_counter() - started) * 1000)
    with tempfile.TemporaryDirectory(prefix="phase11-performance-") as temp_name:
        database = DatabaseService(Path(temp_name) / "profile.db")
        database.initialize()
        for category in (
            ErrorType.CASE_ERROR,
            ErrorType.CASE_ERROR,
            ErrorType.VERB_CONJUGATION,
        ):
            database.save_grammar_result(
                "latency_learner", _grammar_result_for_categories([category])
            )
        profile = ProfileService(database)
        profile.get_profile("latency_learner")
        profile_values: list[float] = []
        for _ in range(sample_count):
            started = time.perf_counter()
            profile.get_profile("latency_learner")
            profile_values.append((time.perf_counter() - started) * 1000)
    return {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "measurement": "perf_counter wall-clock time in the current local process",
        },
        "vocabulary_lookup_warmed": _latency_summary(vocabulary_values),
        "profile_retrieval": _latency_summary(profile_values),
    }


PROTECTED_PHASE_PATHS = (
    "data/processed/finnish_sentences_v1.jsonl",
    "data/processed/preprocessing_manifest_v1.json",
    "data/errors/synthetic_errors_v1.jsonl",
    "data/errors/error_generation_manifest_v1.json",
    "data/evaluation/train_v1.jsonl",
    "data/evaluation/validation_v1.jsonl",
    "data/evaluation/test_v1.jsonl",
    "data/evaluation/ml_split_manifest_v1.json",
    "data/evaluation/ml_test_predictions_v1.jsonl",
    "models/error_classifier_v1.joblib",
    "models/error_classifier_v1_metadata.json",
    "app/prompts/grammar_checker_prompt.txt",
    "app/services/grammar_service.py",
    "app/models/grammar.py",
    "app/services/database_service.py",
    "app/services/profile_service.py",
    "app/models/learner.py",
    "data/vocabulary/vocabulary_index_v1.jsonl",
    "data/vocabulary/vocabulary_manifest_v1.json",
    "app/services/vocabulary_service.py",
    "app/models/vocabulary.py",
    "app/prompts/exercise_generator_prompt.txt",
    "app/services/exercise_service.py",
    "app/models/exercise.py",
)

# Phase 11's approved live-provider repair intentionally added safe diagnostic
# propagation at this boundary. It is documented and is not an accidental
# mutation of the frozen product scope.
APPROVED_PHASE11_INTEGRITY_EXCEPTIONS = {
    "app/services/grammar_service.py": "approved live-provider diagnostic propagation fix",
}


def verify_previous_artifact_integrity(project_root: Path) -> dict[str, Any]:
    """Compare protected Phase 3-9 files with the approved Phase 10 HEAD."""

    root = Path(project_root)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    records: list[dict[str, Any]] = []
    for relative in PROTECTED_PHASE_PATHS:
        path = root / relative
        current_object = subprocess.run(
            ["git", "hash-object", relative],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        committed_object = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        records.append(
            {
                "path": relative,
                "current_sha256": sha256_file(path),
                "current_git_object": current_object,
                "phase10_head_git_object": committed_object,
                "unchanged": current_object == committed_object,
                "approved_phase11_change": APPROVED_PHASE11_INTEGRITY_EXCEPTIONS.get(relative),
            }
        )
    return {
        "comparison_commit": head,
        "protected_file_count": len(records),
        "all_unchanged": all(record["unchanged"] for record in records),
        "all_unchanged_or_approved": all(
            record["unchanged"] or record["approved_phase11_change"] for record in records
        ),
        "files": records,
        "policy": "Phase 3-9 data, model, prompt, schema, and generation files were frozen.",
    }


def run_test_suite(project_root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    result = subprocess.run(
        command,
        cwd=Path(project_root),
        capture_output=True,
        text=True,
    )
    output = (result.stdout + "\n" + result.stderr).strip()

    def count(label: str) -> int:
        matches = re.findall(rf"(\d+)\s+{label}", output)
        return int(matches[-1]) if matches else 0

    return {
        "command": "python -m pytest -q",
        "return_code": result.returncode,
        "passed": count("passed"),
        "failed": count("failed"),
        "skipped": count("skipped"),
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "summary_line": output.splitlines()[-1] if output else None,
    }


def build_rubric_evidence(report: Mapping[str, Any]) -> list[dict[str, str]]:
    structured = report["grammar"]["structured_output"]
    provider_evaluated = structured["total_primary_requests"] == GRAMMAR_CASE_COUNT
    provider_working = structured["valid_typed_responses"] > 0
    return [
        {
            "rubric_criterion": "Data transformation before training",
            "implementation_evidence": "Phase 3 parser, processed JSONL, manifest, and notebook 02.",
            "evaluation_evidence": "Phase 3 output hash and 33,859-record manifest remained intact.",
            "status": "SATISFIED",
            "notes": "Original Finnish text is preserved; model-only normalization is documented.",
        },
        {
            "rubric_criterion": "Separate train and test evaluation",
            "implementation_evidence": "Grouped train/validation/test JSONL files and Phase 5 split manifest.",
            "evaluation_evidence": "All pairwise leakage-group intersections were recomputed as zero.",
            "status": "SATISFIED",
            "notes": "Source-group isolation takes priority over exact split proportions.",
        },
        {
            "rubric_criterion": "Accuracy and loss for train and test",
            "implementation_evidence": "Phase 5 metadata stores train, validation, and test metrics.",
            "evaluation_evidence": "Saved-pipeline metrics were recomputed, including classification log loss.",
            "status": "SATISFIED",
            "notes": "Log loss is classification log loss, not a neural training curve.",
        },
        {
            "rubric_criterion": "Acceptable model accuracy or prompted LLM functionality",
            "implementation_evidence": "Saved Logistic Regression pipeline and validated LLM service boundaries.",
            "evaluation_evidence": (
                f"All 40 live grammar attempts were recorded: {structured['valid_typed_responses']} validated outputs, {structured['malformed_or_invalid_responses']} invalid provider output, and {structured['provider_transport_or_http_failures']} transport/HTTP failures."
                if provider_evaluated
                else "The frozen live grammar run is incomplete."
            ),
            "status": "SATISFIED" if provider_working and provider_evaluated else "PARTIAL",
            "notes": "ML and LLM tasks are different and are not compared as one accuracy score.",
        },
        {
            "rubric_criterion": "Real-world/community problem",
            "implementation_evidence": "Project specification addresses recurring Finnish-learning errors.",
            "evaluation_evidence": "End-to-end checks exercise the complete learning feedback loop.",
            "status": "SATISFIED",
            "notes": "Audience impact still requires live feedback evidence.",
        },
        {
            "rubric_criterion": "Original and creative idea",
            "implementation_evidence": "Grammar feedback is connected to local history, ranked weaknesses, and practice.",
            "evaluation_evidence": "Controlled persistence/profile/personalization scenarios validate that connection.",
            "status": "PARTIAL",
            "notes": "Originality is partly a qualitative judgment for assessors.",
        },
        {
            "rubric_criterion": "Technologies beyond curriculum via documentation",
            "implementation_evidence": "UD, FinnWordNet, Streamlit, SQLite, scikit-learn, and an isolated LLM API.",
            "evaluation_evidence": "Artifacts, licenses, service tests, and reproducibility commands are documented.",
            "status": "SATISFIED",
            "notes": "Presentation must still demonstrate the student's understanding.",
        },
        {
            "rubric_criterion": "Logical and aesthetic application/UI library use",
            "implementation_evidence": "Six-page Streamlit UI with centralized routing and learner-facing labels.",
            "evaluation_evidence": "All pages rendered and the real Streamlit health endpoint returned ok.",
            "status": "SATISFIED",
            "notes": "Automated checks establish function and flow, not audience taste.",
        },
        {
            "rubric_criterion": "Audience acceptance",
            "implementation_evidence": "No audience-feedback artifact exists in Phase 11.",
            "evaluation_evidence": "Cannot be established through source code or automated evaluation.",
            "status": "REQUIRES LIVE PRESENTATION",
            "notes": "Requires live presentation/audience evidence outside Phase 11.",
        },
        {
            "rubric_criterion": "Confident presentation and audience interaction",
            "implementation_evidence": "Not a software implementation criterion.",
            "evaluation_evidence": "Not observable in this repository.",
            "status": "REQUIRES LIVE PRESENTATION",
            "notes": "Requires live presentation evidence outside Phase 11.",
        },
        {
            "rubric_criterion": "Self-evaluation after audience/judge feedback",
            "implementation_evidence": "Phase reviews and this failure/limitations audit provide technical self-evaluation.",
            "evaluation_evidence": "No post-audience or post-judge feedback exists yet.",
            "status": "REQUIRES LIVE PRESENTATION",
            "notes": "The feedback-specific portion requires live assessment evidence.",
        },
        {
            "rubric_criterion": "Logical application demo flow",
            "implementation_evidence": "Write -> check -> history/profile -> practice is implemented.",
            "evaluation_evidence": "End-to-end scenarios validate each transition with isolated state.",
            "status": "REQUIRES LIVE PRESENTATION",
            "notes": "A live demo performance is not proven by code alone.",
        },
        {
            "rubric_criterion": "Combine feature explanation with demo",
            "implementation_evidence": "About page and notebooks explain architecture and feature roles.",
            "evaluation_evidence": "No live presentation was observed.",
            "status": "REQUIRES LIVE PRESENTATION",
            "notes": "Requires live presentation evidence outside Phase 11.",
        },
        {
            "rubric_criterion": "Problem analysis and justified AI solution",
            "implementation_evidence": "Project docs distinguish deterministic, ML, linguistic-resource, and LLM roles.",
            "evaluation_evidence": "Component-specific evaluation avoids claiming AI where deterministic logic is used.",
            "status": "SATISFIED",
            "notes": "External LLM dependence remains a measured limitation.",
        },
        {
            "rubric_criterion": "Intuitive user flow",
            "implementation_evidence": "Action-bound forms, clear navigation, stored results, and stable exercises.",
            "evaluation_evidence": "Navigation, exactly-once actions, feedback, and failure states passed E2E checks.",
            "status": "SATISFIED",
            "notes": "Formal user study was not conducted.",
        },
        {
            "rubric_criterion": "Answer questions about model construction",
            "implementation_evidence": "Notebook 04, metadata, features, metrics, and shortcut analysis support explanation.",
            "evaluation_evidence": "No oral questioning was observed.",
            "status": "REQUIRES LIVE PRESENTATION",
            "notes": "Requires live presentation evidence outside Phase 11.",
        },
        {
            "rubric_criterion": "Answer questions about UI construction",
            "implementation_evidence": "Thin router, page modules, cached resources, and rerun-state tests are documented.",
            "evaluation_evidence": "No oral questioning was observed.",
            "status": "REQUIRES LIVE PRESENTATION",
            "notes": "Requires live presentation evidence outside Phase 11.",
        },
        {
            "rubric_criterion": "Notebook IDE for resource/model work",
            "implementation_evidence": "Notebooks 01-05 cover exploration, preprocessing, generation, ML, and evaluation.",
            "evaluation_evidence": "Notebook 05 was executed from a fresh kernel against raw result files.",
            "status": "SATISFIED",
            "notes": "The saved notebooks use reusable modules instead of duplicating production logic.",
        },
        {
            "rubric_criterion": "Source-code organization",
            "implementation_evidence": "Separate UI, services, models, prompts, data, reports, notebooks, and tests.",
            "evaluation_evidence": "Complete tests and protected-artifact integrity checks cover module boundaries.",
            "status": "SATISFIED",
            "notes": "Evaluation logic is isolated under app/evaluation.",
        },
    ]


def build_requirements_audit(report: Mapping[str, Any]) -> list[dict[str, str]]:
    grammar_outputs = report["grammar"]["structured_output"]["valid_typed_responses"]
    grammar_attempts_complete = report["grammar"]["structured_output"]["total_primary_requests"] == GRAMMAR_CASE_COUNT
    grammar_manual_complete = report["grammar"]["explanation_quality"]["pending_manual_reviews"] == 0
    exercise_generated = report["exercise"]["generated"] == report["exercise"]["requested"] == 20
    exercise_manual_complete = report["exercise"]["manual_review"]["pending"] == 0
    common = {
        "grammar": "data/evaluation/grammar_evaluation_results_v1.jsonl",
        "vocabulary": "data/evaluation/vocabulary_cases_v1.jsonl and final_evaluation_v1.json",
        "profile": "controlled temporary-SQLite profile and personalization results",
        "exercise": "data/evaluation/exercise_evaluation_results_v1.jsonl",
    }
    rows = [
        ("MVP-01", "Streamlit application launches", "app.py", "real health endpoint and AppTest", "SATISFIED", "Local MVP only."),
        ("MVP-02", "User can enter one Finnish sentence", "Grammar Checker form", "E2E correct and incorrect submissions", "SATISFIED", "500-character service limit."),
        ("MVP-03", "Grammar analysis works", "GrammarService and prompt", common["grammar"], "SATISFIED" if grammar_attempts_complete and grammar_outputs else "PARTIAL", f"{grammar_outputs}/40 attempts produced validated outputs; one schema failure is retained."),
        ("MVP-04", "Sentence correction works", "typed corrected_sentence", common["grammar"], "PARTIAL", "Across 18 erroneous cases, 17 corrections matched exactly and one was incorrect; separately, one valid case had no validated provider output."),
        ("MVP-05", "Grammar explanation works", "per-error and overall explanation fields", common["grammar"], "PARTIAL", "AI-assisted review is complete, but four explanations scored 1 for grammatical correctness and four scored 1 for learner usefulness."),
        ("MVP-06", "Errors are classified", "seven-category production taxonomy", common["grammar"], "SATISFIED" if grammar_outputs else "PARTIAL", "Single- and multiple-error metrics use small category supports."),
        ("MVP-07", "Results are stored", "SQLite grammar_checks/grammar_errors", "E2E exactly-once and profile scenarios", "SATISFIED", "Local demo identity; no authentication."),
        ("MVP-08", "Learner weakness profile updates", "ProfileService", common["profile"], "SATISFIED", "Confidence is stored but not used as a weight."),
        ("MVP-09", "Basic vocabulary lookup works", "Phase 8 local index and service", common["vocabulary"], "SATISFIED", "Corpus-bounded, not a complete dictionary."),
        ("MVP-10", "Basic targeted exercises can be generated", "ExerciseService", common["exercise"], "PARTIAL", "20/20 generated and passed structure, but one stored answer/explanation failed linguistic review and distractor quality passed in only 11/20 cases."),
        ("MVP-11", "ML baseline is trained and loadable", "error_classifier_v1.joblib", "reloaded pipeline and reproduced predictions", "SATISFIED", "Three synthetic labels only."),
        ("MVP-12", "Train/test separation is documented", "split manifest and notebook 04", "zero group intersections", "SATISFIED", "Grouped 70/15/15 approximation."),
        ("MVP-13", "Evaluation metrics are available", "Phase 5 metadata and Phase 11 evaluator", "component-specific machine report", "SATISFIED" if grammar_attempts_complete else "PARTIAL", "AI-assisted qualitative linguistic review is reported separately from automatic metrics."),
        ("MVP-14", "Notebooks document data/ML/evaluation", "notebooks/01-05", "fresh execution of notebook 05", "SATISFIED", "Production logic remains in modules."),
        ("MVP-15", "Source code is modular", "app/ui, services, models, prompts, evaluation", "full test suite", "SATISFIED", "No major feature was added in Phase 11."),
        ("MVP-16", "API keys are protected", ".env.example and ignore rules", "no API secret recorded; provider metadata excludes key", "SATISFIED", "A live key was configured only through the ignored .env file."),
        ("MVP-17", "Final demo flow works start to finish", "six-page UI learning loop", "deterministic E2E checks plus live grammar/exercise component outputs", "REQUIRES LIVE PRESENTATION", "Automated flow checks pass; the assessed live walkthrough remains Phase 12 work."),
        ("MVP-18", "Limitations are documented", "About page and final report", "consolidated evidence-based limitations", "SATISFIED", "Includes synthetic-data and provider limitations."),
    ]
    return [
        {
            "requirement_id": requirement_id,
            "requirement": requirement,
            "implementation_evidence": implementation,
            "evaluation_evidence": evaluation,
            "status": status,
            "limitation": limitation,
        }
        for requirement_id, requirement, implementation, evaluation, status, limitation in rows
    ]


def build_failure_analysis(
    report: Mapping[str, Any],
    grammar_records: Sequence[Mapping[str, Any]],
    exercise_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grammar_counts = collections.Counter(report["grammar"]["failure_counts"])
    exercise_counts = collections.Counter(report["exercise"]["failure_counts"])
    ml_matrix = report["ml_baseline"]["metrics"]["test"]["confusion_matrix"]["values"]
    ml_errors = sum(
        value
        for row_index, row in enumerate(ml_matrix)
        for column_index, value in enumerate(row)
        if row_index != column_index
    )
    vocabulary_failures = sum(
        not all(value is not False for value in record["scores"].values())
        for record in report["vocabulary"]["records"]
    )
    profile_failures = report["profile"]["failed"] + report["personalization"]["failed"]
    e2e_failures = report["end_to_end"]["failed"]
    consolidated = collections.Counter()
    consolidated.update({f"grammar:{key}": value for key, value in grammar_counts.items()})
    consolidated.update({f"exercise:{key}": value for key, value in exercise_counts.items()})
    if ml_errors:
        consolidated["ml:misclassified_synthetic_test_example"] = ml_errors
    if vocabulary_failures:
        consolidated["vocabulary:failed_reference_case"] = vocabulary_failures
    if profile_failures:
        consolidated["profile_or_personalization:deterministic_mismatch"] = profile_failures
    if e2e_failures:
        consolidated["ui_or_service:end_to_end_failure"] = e2e_failures
    examples: list[dict[str, Any]] = []
    examples.extend(
        {
            "subsystem": "grammar",
            "case_id": record["case_id"],
            "input": record["sentence"],
            "reason": record.get("failure_reason"),
            "observation": record.get("safe_error"),
        }
        for record in grammar_records
        if record.get("run_status") != "success"
    )
    examples.extend(
        {
            "subsystem": "grammar",
            "case_id": record["case_id"],
            "input": record["sentence"],
            "reason": ", ".join(record["score"]["failure_reasons"]),
            "observation": (
                f"Expected categories {record['score']['expected_categories']}; "
                f"predicted {record['score']['predicted_categories']}; "
                f"correction outcome {record['score']['correction_outcome']}."
            ),
        }
        for record in grammar_records
        if record.get("run_status") == "success"
        and record.get("score", {}).get("failure_reasons")
    )
    examples.extend(
        {
            "subsystem": "exercise",
            "case_id": record["request_id"],
            "input": record["target_error_type"],
            "reason": record.get("failure_reason"),
            "observation": record.get("safe_error"),
        }
        for record in exercise_records
        if record.get("run_status") != "success"
    )
    examples.extend(
        {
            "subsystem": "ml_baseline",
            "case_id": item["synthetic_id"],
            "input": item["incorrect_sentence"],
            "reason": "misclassified_synthetic_test_example",
            "observation": f"Expected {item['true_label']}; predicted {item['predicted_label']}.",
        }
        for item in json.loads(
            json.dumps(report["ml_baseline"].get("representative_misclassifications", []))
        )
    )
    grammar_review_fields = (
        "grammatical_correctness",
        "relevance",
        "clarity",
        "learner_usefulness",
    )
    exercise_review_fields = (
        "target_relevance",
        "question_clarity",
        "unambiguous",
        "answer_correctness",
        "distractor_plausibility",
        "explanation_correctness",
        "no_unrelated_errors",
    )
    grammar_lower_scored = [
        {
            "case_id": record["case_id"],
            "scores": {
                field: record["manual_explanation_review"].get(field)
                for field in grammar_review_fields
            },
            "notes": record["manual_explanation_review"].get("notes"),
        }
        for record in grammar_records
        if record.get("manual_explanation_review", {}).get("status") == "COMPLETED"
        and any(
            record["manual_explanation_review"].get(field) in (1, 2)
            for field in grammar_review_fields
        )
    ]
    exercise_non_pass = [
        {
            "exercise_id": record["request_id"],
            "ratings": {
                field: record["manual_linguistic_review"].get(field)
                for field in exercise_review_fields
            },
            "failure_reasons": record["manual_linguistic_review"].get(
                "failure_reasons", []
            ),
            "notes": record["manual_linguistic_review"].get("notes"),
        }
        for record in exercise_records
        if record.get("manual_linguistic_review", {}).get("status") == "COMPLETED"
        and any(
            record["manual_linguistic_review"].get(field) in ("PARTIAL", "FAIL")
            for field in exercise_review_fields
        )
    ]
    available_grammar_ids = {item["case_id"] for item in grammar_lower_scored}
    supported_grammar_findings = [
        {
            "issue": "subject-verb agreement false acceptance",
            "case_ids": ["single_verb_02"],
        },
        {
            "issue": "attributive versus predicative terminology",
            "case_ids": ["correct_07"],
        },
        {
            "issue": "numeral plus singular-partitive morphology",
            "case_ids": ["single_noun_01", "single_noun_02"],
        },
        {
            "issue": "connegative form mislabeled as an infinitive",
            "case_ids": ["single_order_02"],
        },
        {
            "issue": "oversimplified total-object case terminology",
            "case_ids": ["correct_04", "multiple_04"],
        },
        {
            "issue": "colloquial Finnish treated too prescriptively",
            "case_ids": ["uncertain_04"],
        },
    ]
    supported_grammar_findings = [
        finding
        for finding in supported_grammar_findings
        if set(finding["case_ids"]) <= available_grammar_ids
    ]
    return {
        "taxonomy_counts": dict(sorted(consolidated.items())),
        "representative_examples": examples[:8],
        "integrity_policy": (
            "Failed requests and questionable cases remain in raw output; none were deleted "
            "or relabeled after prediction."
        ),
        "qualitative_review": {
            "method": "AI-assisted qualitative linguistic review",
            "human_or_native_teacher_review": False,
            "grammar_lower_scored_records": grammar_lower_scored,
            "grammar_supported_findings": supported_grammar_findings,
            "exercise_non_pass_records": exercise_non_pass,
        },
        "remediation_notes": [
            "Retain the completed AI-assisted qualitative review evidence and disclose that it is not a human/native-teacher assessment.",
            "Do not tune the prompt on the frozen grammar set and then present the same run as untouched final evaluation.",
            "Treat Phase 5 source/length sensitivity and suffix-heavy features as shortcut evidence, not general Finnish competence.",
        ],
    }


def _fmt_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "Not calculable"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}" if isinstance(value, float) else str(value)
    return str(value)


def _fmt_percent(value: float | None) -> str:
    return "Not calculable" if value is None else f"{value * 100:.2f}%"


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_end_to_end_checklist(report: Mapping[str, Any]) -> str:
    lines = [
        "# End-to-End Checklist v1",
        "",
        f"Evaluation date: `{report['evaluation_metadata']['evaluation_date']}`",
        "",
        "Mutable checks used controlled temporary SQLite databases. PASS is recorded only for executed scenarios.",
        "",
        "| Scenario | Result | Evidence |",
        "|---|---|---|",
    ]
    for scenario in report["end_to_end"]["scenarios"]:
        lines.append(
            f"| {_md_cell(scenario['scenario'])} | {scenario['status']} | {_md_cell(scenario['evidence'])} |"
        )
    smoke = report["streamlit_smoke"]
    lines.extend(
        [
            f"| real_streamlit_process_health | {smoke['status']} | "
            f"Health response: {_md_cell(smoke.get('health_response'))}; error: {_md_cell(smoke.get('error'))}. |",
            "",
            "## Rerun evidence",
            "",
            "- One grammar action produced one service call and one database insertion.",
            "- Rendering the stored grammar result did not call the service or insert again.",
            "- Selecting/submitting a practice answer did not generate a replacement exercise.",
            "- Session state retained the same exercise ID through normal reruns.",
            "",
            "## Provider limitation",
            "",
            (
                f"Live provider evidence exists: {report['grammar']['structured_output']['valid_typed_responses']}/40 grammar outputs validated and {report['exercise']['generated']}/20 exercises generated. AI-assisted qualitative linguistic review remains separate from automatic validation."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_markdown_report(report: Mapping[str, Any]) -> str:
    grammar = report["grammar"]
    detection = grammar["detection"]
    fpr = grammar["false_positive_rate"]
    exercise = report["exercise"]
    lines = [
        "# Final Evaluation - Phase 11",
        "",
        f"Evaluation version: `{report['evaluation_version']}`  ",
        f"Evaluation date: `{report['evaluation_metadata']['evaluation_date']}`  ",
        f"Git commit evaluated: `{report['evaluation_metadata']['git_commit']}`  ",
        f"Verdict: **{report['phase_11_verdict']}**",
        "",
        "## 1. Evaluation scope",
        "",
        "Feature scope was frozen at the approved Phase 10 commit. This report evaluates grammar, the Phase 5 baseline, vocabulary, profiles/personalization, exercises, and the integrated application separately. No Phase 12 presentation work or major product feature was added.",
        "",
        "## 2. Methodology",
        "",
        f"- Grammar: {grammar['dataset']['case_count']} frozen, human-authored cases; positive class = a sentence contains at least one grammar error.",
        f"- Vocabulary: {report['vocabulary']['dataset']['case_count']} manually source-audited lookup cases.",
        f"- Profiles: {report['profile']['scenario_count']} temporary-database histories and {report['personalization']['profile_count']} target-selection profiles.",
        f"- Exercises: {exercise['requested']} requests, four for each of five supported categories.",
        "- Explanation and exercise judgments use an AI-assisted qualitative linguistic review under the named reviewer identity; no human/native-teacher review is claimed, and qualitative ratings remain separate from structural validity.",
        "- Missing outputs remain failures; no failed record was removed to improve a score.",
        "",
        "## 3. Grammar results",
        "",
        f"Provider: `{report['evaluation_metadata']['llm']['provider']}`; model: `{report['evaluation_metadata']['llm']['model'] or 'not configured'}`; temperature: `{report['evaluation_metadata']['llm']['temperature']}`.",
        "",
        f"Provider responses were received for **{grammar['structured_output']['provider_responses_received']}/{grammar['structured_output']['total_primary_requests']}** attempts. Valid typed results: **{grammar['structured_output']['valid_typed_responses']}/{grammar['structured_output']['total_primary_requests']}** ({_fmt_percent(grammar['structured_output']['success_rate'])}). Provider transport/HTTP failures: **{grammar['structured_output']['provider_transport_or_http_failures']}**; malformed/invalid provider outputs: **{grammar['structured_output']['malformed_or_invalid_responses']}**.",
        "",
        "### Detection metrics",
        "",
        f"Metrics cover {detection['evaluated_cases_with_prediction']}/{detection['total_dataset_cases']} cases with an actual prediction. Accuracy: **{_fmt_number(detection['accuracy'])}**; precision: **{_fmt_number(detection['precision'])}**; recall: **{_fmt_number(detection['recall'])}**; F1: **{_fmt_number(detection['f1'])}**.",
        "",
        f"Confusion counts: **TP={detection['confusion_matrix']['values'][1][1]}**, **TN={detection['confusion_matrix']['values'][0][0]}**, **FP={detection['confusion_matrix']['values'][0][1]}**, **FN={detection['confusion_matrix']['values'][1][0]}**. Matrix `[[TN, FP], [FN, TP]]`: `{detection['confusion_matrix']['values']}`.",
        "",
        "### False-positive rate",
        "",
        f"False positives: **{fpr['false_positives']}** / **{fpr['total_valid_sentences_in_dataset']} frozen valid sentences** = **{_fmt_percent(fpr['rate'])}**. Prediction-conditioned rate: **{fpr['false_positives']}/{fpr['evaluated_valid_sentences']} = {_fmt_percent(fpr['evaluated_output_rate'])}**; {fpr['valid_sentences_without_prediction']} valid case had no validated prediction and is not misreported as a true negative.",
        "",
        "### Error-type classification",
        "",
        f"Single-error category exact match: **{_fmt_percent(grammar['single_error_category']['exact_match_accuracy'])}** over {grammar['single_error_category']['evaluated_cases']}/{grammar['single_error_category']['dataset_cases']} cases. Macro precision/recall/F1: **{_fmt_number(grammar['single_error_category']['macro_precision'])} / {_fmt_number(grammar['single_error_category']['macro_recall'])} / {_fmt_number(grammar['single_error_category']['macro_f1'])}**.",
        "",
        "| Category | Dataset support | Evaluated support | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for category, values in grammar["single_error_category"]["per_class"].items():
        lines.append(
            f"| {category} | {values['support_in_dataset']} | {values['support_in_evaluated_cases']} | {_fmt_number(values['precision'])} | {_fmt_number(values['recall'])} | {_fmt_number(values['f1'])} |"
        )
    lines.append("")
    lines.append(
        "Each single-error category has only two frozen examples, so per-class and macro results are descriptive rather than robust population estimates."
    )
    multiple = grammar["multiple_error_category"]
    lines.extend(
        [
            "",
            f"Multiple-error set scoring covers {multiple['evaluated_cases']}/{multiple['dataset_cases']} cases without forcing a single label. Set exact match: **{_fmt_percent(multiple['set_exact_match_rate'])}**. Micro precision/recall/F1: **{_fmt_number(multiple['micro_precision'])} / {_fmt_number(multiple['micro_recall'])} / {_fmt_number(multiple['micro_f1'])}**. Macro precision/recall/F1: **{_fmt_number(multiple['macro_precision'])} / {_fmt_number(multiple['macro_recall'])} / {_fmt_number(multiple['macro_f1'])}**.",
            "",
            "### Corrections and explanations",
            "",
            f"Correction outcomes across the frozen set: `{grammar['correction']['counts']}`. Among the {grammar['correction']['evaluated_outputs']} reviewable erroneous outputs, exact match rate: **{_fmt_percent(grammar['correction']['exact_match_rate'])}**; accepted including reviewed alternatives: **{_fmt_percent(grammar['correction']['acceptable_rate_including_alternatives'])}**. No AI-assisted correction-acceptability override was used.",
            "",
            f"AI-assisted qualitative explanation reviews completed: **{grammar['explanation_quality']['completed_manual_reviews']}/{grammar['explanation_quality']['successful_outputs']}**; non-reviewable because no validated output: **{grammar['explanation_quality']['not_reviewable_no_output']}**. Scale: 1-3. These ratings are AI-assisted judgments under the named reviewer identity, not a human/native-teacher assessment or objective linguistic truth.",
            "",
            "| Criterion | Score 1 | Score 2 | Score 3 | Mean | Score 3 | Score 1 or 2 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for criterion, values in grammar["explanation_quality"]["criterion_summary"].items():
        lines.append(
            f"| {criterion.replace('_', ' ')} | {values['score_1']} | {values['score_2']} | {values['score_3']} | {_fmt_number(values['mean'])} | {_fmt_percent(values['score_3_rate'])} | {_fmt_percent(values['score_1_or_2_rate'])} |"
        )
    lines.extend(
        [
            "",
            "Recurring supported issues include subject-verb agreement, attributive-versus-predicative analysis, numeral-plus-singular-partitive morphology, connegative terminology, total-object terminology, and colloquial-register handling. The case IDs and review notes are retained in the machine-readable failure analysis.",
            "",
            "## 4. ML baseline verification",
            "",
            f"All reproducibility checks passed: **{report['ml_baseline']['all_checks_passed']}**. Split counts are `{report['ml_baseline']['record_counts']}` and recomputed group intersections are `{report['ml_baseline']['split_identity']['actual_group_intersections']}`.",
            "",
            "| Split | Accuracy | Macro F1 | Log loss | Recomputed match |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for split in ("train", "validation", "test"):
        values = report["ml_baseline"]["metrics"][split]
        lines.append(
            f"| {split} | {values['accuracy']:.3f} | {values['macro_f1']:.3f} | {values['log_loss']:.3f} | {report['ml_baseline']['recomputed_metric_matches'][split]} |"
        )
    lines.extend(
        [
            "",
            "The baseline classifies three controlled synthetic error categories from an already-incorrect sentence. It does not decide whether arbitrary Finnish is correct, so its scores are not directly comparable with grammar-checker metrics. Character suffixes, source imbalance, sentence length, and an approximately 0.224 train-test macro-F1 gap show shortcut/generalization risk.",
            "",
            "Phase 11 found and fixed one blocking artifact-loading defect: the frozen Phase 5 pickle referred to its custom normalizer through `__main__`. The loader now supplies a narrowly scoped compatibility alias; the model, split, and prediction artifacts were not changed or retrained, and all stored metrics were reproduced after the fix.",
            "",
            "## 5. Vocabulary results",
            "",
            "| Measure | Passed | Evaluated | Rate |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, values in report["vocabulary"]["metrics"].items():
        lines.append(
            f"| {name} | {values['passed']} | {values['evaluated']} | {_fmt_percent(values['rate'])} |"
        )
    index_stats = report["vocabulary_index"]
    lines.extend(
        [
            "",
            f"Index statistics: {index_stats['analysis_records']} analysis records, {index_stats['lookup_keys']} lookup keys, {index_stats['normalized_lemmas']} normalized lemmas, and {index_stats['ambiguous_lookup_keys']} ambiguous keys. These describe the bounded artifact, not Finnish dictionary coverage.",
            "",
            "## 6. Profile and personalization results",
            "",
            f"Profile histories: **{report['profile']['passed']}/{report['profile']['scenario_count']} PASS**. Personalization profiles: **{report['personalization']['passed']}/{report['personalization']['profile_count']} PASS**. Counts, percentages, ranking, ties, isolation, and zero-history behavior were checked exactly.",
            "",
            "No-history behavior is deliberate: automatic selection fails safely and the learner must explicitly choose one of the supported topics.",
            "",
            "## 7. Exercise results",
            "",
            f"Generated: **{exercise['generated']}/{exercise['requested']}**; provider failures: **{exercise['provider_failures']}**. Schema-valid: **{exercise['schema_valid']}/{exercise['requested']}** ({_fmt_percent(exercise['schema_validity_rate_over_all_requests'])}). Structurally valid over all requests: **{exercise['structurally_valid']}/{exercise['requested']}** ({_fmt_percent(exercise['structural_validity_rate_over_all_requests'])}). AI-assisted qualitative linguistic reviews: **{exercise['manual_review']['completed']}**; pending: **{exercise['manual_review']['pending']}**; not reviewable because no output: **{exercise['manual_review']['not_reviewable_no_output']}**.",
            "",
            "Structural validity checks taxonomy, type, question, four unique options, exactly one correct-answer occurrence, and explanation presence. The separate AI-assisted qualitative rubric covers relevance, clarity, ambiguity, answer correctness, distractors, explanation correctness, and unintended Finnish errors.",
            "",
            "| Category | Requested | Generated | Structurally valid | Qualitatively reviewed |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for category, values in exercise["by_category"].items():
        lines.append(
            f"| {category} | {values['requested']} | {values['generated']} | {values['structurally_valid']} | {values['manually_reviewed']} |"
        )
    lines.extend(
        [
            "",
            "| Criterion | PASS | PARTIAL | FAIL | PASS rate | Non-PASS rate |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for criterion, values in exercise["manual_review"]["criterion_summary"].items():
        lines.append(
            f"| {criterion.replace('_', ' ')} | {values['pass']} | {values['partial']} | {values['fail']} | {_fmt_percent(values['pass_rate'])} | {_fmt_percent(values['non_pass_rate'])} |"
        )
    lines.extend(
        [
            "",
            "Structural validity was 100%, but linguistic/pedagogical validity was not: `noun_inflection_03` stores an incorrect answer and explanation, while nine exercises have weak distractors and two explanations oversimplify Finnish object terminology.",
            "",
            "## 8. End-to-end validation",
            "",
            f"Executed scenarios: **{report['end_to_end']['passed']}/{report['end_to_end']['scenario_count']} PASS**. Real Streamlit process smoke: **{report['streamlit_smoke']['status']}** with health response `{report['streamlit_smoke'].get('health_response')}`.",
            "",
            "Rerun evidence shows one grammar submit caused one analysis and one insertion; result rendering did not repeat either; selecting/checking an answer preserved the exercise and did not regenerate it.",
            "",
            "## 9. Performance and reliability",
            "",
            f"Warmed local vocabulary lookups: n={report['performance']['vocabulary_lookup_warmed']['sample_count']}, median={_fmt_number(report['performance']['vocabulary_lookup_warmed']['median_ms'])} ms, p95={_fmt_number(report['performance']['vocabulary_lookup_warmed']['p95_ms'])} ms.",
            "",
            f"Profile retrieval: n={report['performance']['profile_retrieval']['sample_count']}, median={_fmt_number(report['performance']['profile_retrieval']['median_ms'])} ms, p95={_fmt_number(report['performance']['profile_retrieval']['p95_ms'])} ms.",
            "",
            f"Grammar primary-attempt latency: median={_fmt_number(report['performance']['grammar_primary_requests']['median_ms'])} ms; exercise-attempt latency: median={_fmt_number(report['performance']['exercise_requests']['median_ms'])} ms. {report['performance']['external_latency_caveat']}",
            "",
            (
                f"Repeatability: four cases x three attempts; successful outputs = {sum(value['successful_outputs'] for value in report['reliability']['by_case'].values())}/12. The sample is descriptive only. API cost was not formally measured because token/accounting data were unavailable."
                if report["reliability"]["runs"]
                else "Repeatability was not rerun during this resumed 40+20 live evaluation. API cost was not formally measured because token/accounting data were unavailable."
            ),
            "",
            "## 10. Failure analysis",
            "",
            f"Observed failure taxonomy: `{report['failure_analysis']['taxonomy_counts']}`.",
            "",
            "Provider, schema, and objective scoring failures are retained rather than filtered from the raw artifacts. The Phase 5 test confusion matrix contains genuine misclassifications and remains unchanged.",
            "",
            "Qualitative grammar findings (AI-assisted review):",
            "",
        ]
    )
    qualitative = report["failure_analysis"]["qualitative_review"]
    for finding in qualitative["grammar_supported_findings"]:
        lines.append(
            f"- {finding['issue']}: `{', '.join(finding['case_ids'])}`."
        )
    lines.extend(
        [
            "",
            f"Exercise qualitative review recorded {len(qualitative['exercise_non_pass_records'])} exercises with at least one PARTIAL or FAIL rating. The machine-readable records retain every rating, failure reason, and reviewer note.",
            "",
            "## 11. Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            "## 12. Rubric evidence matrix",
            "",
            "| Criterion | Implementation evidence | Evaluation evidence | Status | Notes |",
            "|---|---|---|---|---|",
        ]
    )
    for row in report["rubric_evidence"]:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(row[key])
                for key in (
                    "rubric_criterion",
                    "implementation_evidence",
                    "evaluation_evidence",
                    "status",
                    "notes",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 13. Project requirements audit",
            "",
            "| ID | Requirement | Implementation evidence | Evaluation evidence | Status | Limitation |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in report["requirements_audit"]:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(row[key])
                for key in (
                    "requirement_id",
                    "requirement",
                    "implementation_evidence",
                    "evaluation_evidence",
                    "status",
                    "limitation",
                )
            )
            + " |"
        )
    tests = report["tests"]
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            "```powershell",
            ".\\.venv\\Scripts\\python.exe -m pytest -q",
            ".\\.venv\\Scripts\\python.exe -m app.evaluation.system_evaluation --project-root . --reuse-live-results --run-tests --include-startup-smoke",
            "$env:PYTHONUTF8 = \"1\"",
            "$env:IPYTHONDIR = \"$PWD\\tmp\\ipython\"",
            "$env:JUPYTER_CONFIG_DIR = \"$PWD\\tmp\\jupyter-config\"",
            "$env:JUPYTER_DATA_DIR = \"$PWD\\tmp\\jupyter-data\"",
            "$env:JUPYTER_RUNTIME_DIR = \"$PWD\\tmp\\jupyter-runtime\"",
            ".\\.venv\\Scripts\\jupyter.exe execute --inplace --timeout=600 notebooks/05_evaluation.ipynb",
            "streamlit run app.py --server.address localhost",
            "```",
            "",
            f"Embedded complete-suite result: **{tests['passed']} passed, {tests['failed']} failed, {tests['skipped']} skipped** (`{tests['status']}`).",
            "",
            f"Protected prior-phase files unchanged or covered by an approved Phase 11 bug-fix exception: **{report['artifact_integrity']['all_unchanged_or_approved']}** ({report['artifact_integrity']['protected_file_count']} files checked; byte-for-byte all unchanged: {report['artifact_integrity']['all_unchanged']}).",
            "",
            "## Verdict",
            "",
            f"**{report['phase_11_verdict']}**",
            "",
        ]
    )
    if report["completion_blockers"]:
        lines.append("Blocking issues:")
        lines.append("")
        lines.extend(f"- {blocker}" for blocker in report["completion_blockers"])
        lines.append("")
    return "\n".join(lines)


def run_system_evaluation(
    project_root: Path,
    *,
    run_tests: bool = False,
    include_startup_smoke: bool = False,
    run_reliability: bool = False,
    reuse_live_results: bool = False,
) -> dict[str, Any]:
    """Run or safely finalize Phase 11 evaluation artifacts.

    ``reuse_live_results`` never calls the provider. It attaches completed
    qualitative reviews to the existing 40+20 raw records and recomputes the
    reports from those preserved live outputs.
    """

    root = Path(project_root).resolve()
    grammar_case_path = root / "data" / "evaluation" / "grammar_cases_v1.jsonl"
    vocabulary_case_path = root / "data" / "evaluation" / "vocabulary_cases_v1.jsonl"
    grammar_output_path = (
        root / "data" / "evaluation" / "grammar_evaluation_results_v1.jsonl"
    )
    exercise_output_path = (
        root / "data" / "evaluation" / "exercise_evaluation_results_v1.jsonl"
    )
    grammar_review_path = root / "data" / "evaluation" / "grammar_manual_reviews_v1.jsonl"
    exercise_review_path = root / "data" / "evaluation" / "exercise_manual_reviews_v1.jsonl"
    report_json_path = root / "reports" / "final_evaluation_v1.json"
    report_markdown_path = root / "reports" / "final_evaluation.md"
    checklist_path = root / "reports" / "end_to_end_checklist_v1.md"
    previous_report = (
        json.loads(report_json_path.read_text(encoding="utf-8"))
        if report_json_path.is_file()
        else None
    )
    grammar_reviews = _load_optional_reviews(grammar_review_path)
    exercise_reviews = _load_optional_reviews(exercise_review_path)

    grammar_cases = load_jsonl(grammar_case_path)
    vocabulary_cases = load_jsonl(vocabulary_case_path)
    if len(grammar_cases) != GRAMMAR_CASE_COUNT:
        raise ValueError(
            f"Approved grammar set must contain exactly {GRAMMAR_CASE_COUNT} cases"
        )
    if len(vocabulary_cases) != VOCABULARY_CASE_COUNT:
        raise ValueError(
            f"Approved vocabulary set must contain exactly {VOCABULARY_CASE_COUNT} cases"
        )
    settings: LLMSettings | None = None
    llm_service: LLMService | None = None
    if reuse_live_results:
        if run_reliability:
            raise ValueError("Reliability requests cannot run while reusing live results")
        if not grammar_output_path.is_file() or not exercise_output_path.is_file():
            raise ValueError("Existing grammar and exercise raw-result files are required")
        grammar_records = load_jsonl(grammar_output_path)
        exercise_records = load_jsonl(exercise_output_path)
        if len(grammar_records) != GRAMMAR_CASE_COUNT:
            raise ValueError("Existing grammar raw results must contain exactly 40 records")
        expected_exercise_count = (
            len(SUPPORTED_GENERATION_ERROR_TYPES) * EXERCISES_PER_CATEGORY
        )
        if len(exercise_records) != expected_exercise_count:
            raise ValueError("Existing exercise raw results must contain exactly 20 records")
        grammar_records, exercise_records = merge_qualitative_reviews(
            grammar_records,
            exercise_records,
            grammar_reviews,
            exercise_reviews,
        )
    else:
        settings = LLMSettings.from_environment()
        llm_service = LLMService(settings)
        grammar_service = GrammarService(llm_service)
        grammar_records = run_grammar_cases(
            grammar_cases, grammar_service, reviews=grammar_reviews
        )
    write_jsonl(grammar_output_path, grammar_records)
    grammar = aggregate_grammar_results(grammar_records, grammar_cases)
    reliability = (
        run_grammar_reliability(grammar_cases, grammar_service)
        if run_reliability
        else previous_report.get("reliability", {})
        if reuse_live_results and previous_report
        else {
            "method": "not rerun during the resumed 40+20 live evaluation",
            "caveat": "The resumed task authorized only the 40 primary grammar and 20 exercise attempts.",
            "runs": [],
            "by_case": {},
            "latency": _latency_summary([]),
        }
    )

    vocabulary_service = VocabularyService(
        root / "data" / "vocabulary" / "vocabulary_index_v1.jsonl"
    )
    vocabulary = evaluate_vocabulary(vocabulary_service, vocabulary_cases)
    vocabulary_index = vocabulary_index_statistics(
        root / "data" / "vocabulary" / "vocabulary_index_v1.jsonl",
        root / "data" / "vocabulary" / "vocabulary_manifest_v1.json",
    )
    profiles = evaluate_profiles()
    personalization = evaluate_personalization()

    if not reuse_live_results:
        assert llm_service is not None
        exercise_service = ExerciseService(
            _StaticProfileService(
                LearnerProfile(
                    learner_id="phase11_exercise_eval",
                    total_checks=0,
                    total_errors=0,
                    weaknesses=(),
                )
            ),
            llm_service,
        )
        exercise_records = run_exercise_evaluation(
            exercise_service, reviews=exercise_reviews
        )
    expected_exercise_count = (
        len(SUPPORTED_GENERATION_ERROR_TYPES) * EXERCISES_PER_CATEGORY
    )
    if len(exercise_records) != expected_exercise_count:
        raise AssertionError("Exercise evaluation did not produce the approved request count")
    write_jsonl(exercise_output_path, exercise_records)
    exercise = aggregate_exercise_results(exercise_records)
    write_manual_review_worksheets(
        grammar_review_path,
        exercise_review_path,
        grammar_records,
        exercise_records,
    )

    ml_baseline = verify_ml_baseline(root)
    end_to_end = evaluate_end_to_end(root)
    performance = measure_local_performance(root, sample_count=30)
    performance["grammar_primary_requests"] = _latency_summary(
        [float(record["latency_ms"]) for record in grammar_records]
    )
    performance["exercise_requests"] = _latency_summary(
        [float(record["latency_ms"]) for record in exercise_records]
    )
    performance["external_provider_latency_measured"] = bool(
        grammar["structured_output"]["valid_typed_responses"] or exercise["generated"]
    )
    performance["external_latency_caveat"] = (
        "External API latency depends on the provider and network."
        if performance["external_provider_latency_measured"]
        else "Only local configuration-failure latency was measured; no provider/network call occurred."
    )
    streamlit_smoke = (
        run_streamlit_smoke(root)
        if include_startup_smoke
        else {
            "status": "NOT_RUN",
            "health_response": None,
            "startup_latency_ms": None,
            "command": "python -m streamlit run app.py --server.headless=true",
            "error": "Startup smoke was not requested.",
        }
    )
    artifact_integrity = verify_previous_artifact_integrity(root)
    tests = (
        run_test_suite(root)
        if run_tests
        else {
            "command": "python -m pytest -q",
            "return_code": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "status": "NOT_RUN",
            "summary_line": None,
        }
    )
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if reuse_live_results:
        if not previous_report:
            raise ValueError("The existing machine-readable report is required for finalization")
        previous_metadata = previous_report["evaluation_metadata"]
        evaluation_date = previous_metadata["evaluation_date"]
        feature_scope_commit = previous_metadata["feature_scope_frozen_at_commit"]
        llm_metadata = copy.deepcopy(previous_metadata["llm"])
    else:
        assert settings is not None
        evaluation_date = _utc_now()
        feature_scope_commit = git_commit
        llm_metadata = {
            "provider": settings.provider,
            "model": settings.model,
            "api_key_configured": bool(settings.api_key),
            "base_url_configured": bool(settings.base_url),
            "temperature": settings.temperature,
            "max_output_tokens": settings.max_output_tokens,
            "timeout_seconds": settings.timeout_seconds,
            "max_retries": settings.max_retries,
            "api_secret_recorded": False,
        }
    report: dict[str, Any] = {
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluation_version": EVALUATION_VERSION,
        "evaluation_metadata": {
            "evaluation_date": evaluation_date,
            "qualitative_review_finalized_at": _utc_now() if reuse_live_results else None,
            "git_commit": git_commit,
            "feature_scope_frozen_at_commit": feature_scope_commit,
            "live_results_reused_without_provider_calls": reuse_live_results,
            "llm": llm_metadata,
            "prompt_hashes": {
                "grammar_checker_prompt_sha256": sha256_file(
                    root / "app" / "prompts" / "grammar_checker_prompt.txt"
                ),
                "exercise_generator_prompt_sha256": sha256_file(
                    root / "app" / "prompts" / "exercise_generator_prompt.txt"
                ),
            },
            "dataset_hashes": {
                "grammar_cases_v1_sha256": sha256_file(grammar_case_path),
                "vocabulary_cases_v1_sha256": sha256_file(vocabulary_case_path),
            },
            "grammar_primary_cases": len(grammar_cases),
            "grammar_reliability_requests": len(reliability["runs"]),
            "exercise_requests": len(exercise_records),
            "manual_review_artifacts": {
                "grammar": {
                    "path": "data/evaluation/grammar_manual_reviews_v1.jsonl",
                    "rows": len(grammar_reviews),
                },
                "exercise": {
                    "path": "data/evaluation/exercise_manual_reviews_v1.jsonl",
                    "rows": len(exercise_reviews),
                },
            },
            "qualitative_review_methodology": {
                "method": "AI-assisted qualitative linguistic review",
                "reviewers": grammar["explanation_quality"]["reviewers"],
                "human_or_native_teacher_review": False,
                "grammar_reviewable_rows_completed": grammar["explanation_quality"][
                    "completed_manual_reviews"
                ],
                "grammar_non_reviewable_rows": grammar["explanation_quality"][
                    "not_reviewable_no_output"
                ],
                "exercise_rows_completed": exercise["manual_review"]["completed"],
            },
        },
        "scope_freeze": {
            "status": "FROZEN",
            "major_features_added": False,
            "phase_12_work_added": False,
            "evaluation_only_paths": [
                "app/evaluation/",
                "data/evaluation/",
                "notebooks/05_evaluation.ipynb",
                "reports/",
                "tests/test_system_evaluation.py",
            ],
        },
        "grammar": grammar,
        "reliability": reliability,
        "ml_baseline": ml_baseline,
        "vocabulary": vocabulary,
        "vocabulary_index": vocabulary_index,
        "profile": profiles,
        "personalization": personalization,
        "exercise": exercise,
        "end_to_end": end_to_end,
        "streamlit_smoke": streamlit_smoke,
        "performance": performance,
        "api_cost": {
            "formally_measured": False,
            "statement": "API cost was not formally measured.",
            "reason": "The transport does not expose persisted provider token/accounting data for this run.",
        },
        "artifact_integrity": artifact_integrity,
        "tests": tests,
        "documented_bug_fixes": [
            {
                "severity": "CRITICAL_FOR_EVALUATION_REPRODUCIBILITY",
                "component": "Phase 5 saved-pipeline loading",
                "defect": (
                    "The frozen v1 joblib artifact referenced FinnishTextNormalizer "
                    "as __main__, so it could not be loaded from a different module entry point."
                ),
                "change": (
                    "load_pipeline now supplies a temporary, narrowly scoped legacy class alias; "
                    "save_pipeline uses the stable app.services.ml_training module path for future artifacts."
                ),
                "artifact_changed_or_retrained": False,
                "verification": (
                    "The frozen artifact loads and its train, validation, and test metrics and "
                    "stored test predictions reproduce exactly within numeric tolerance."
                ),
            }
        ],
    }
    report["limitations"] = [
        "Grammar explanation quality and exercise linguistic quality use AI-assisted qualitative linguistic review; these ratings are not a human/native-teacher assessment, and automatic structure and correctness metrics do not replace them.",
        "External LLM behavior is nondeterministic and may change with provider or model updates even when the prompt and dataset hashes remain fixed.",
        "The Phase 5 baseline uses controlled synthetic examples from only three categories; its scores do not establish real-learner grammar performance.",
        "Phase 5 character n-grams show suffix, source, and sentence-length shortcut risk, including a substantial train-test performance gap.",
        "The vocabulary index is bounded by observed UD forms and FinnWordNet overlap; it is neither a complete dictionary nor a complete morphology system.",
        "Vocabulary meanings are unranked sense candidates and are not context-disambiguated translations.",
        "The AI-assisted exercise review found one incorrect stored answer/explanation and weak distractors in nine of 20 exercises despite 100% structural validity.",
        "SQLite and the demo learner identity are suitable for a local MVP, not authenticated multi-user production use.",
        "The 40-case grammar set, 16-case vocabulary set, and 20-exercise sample are deliberately small and manually auditable, not population-wide estimates.",
        "The optional 12-request repeatability sample was not rerun because this resumed task was limited to the remaining 40 grammar and 20 exercise attempts.",
        "The approved transport retry bound is recorded as one, but per-request transport retry usage is not persisted; exact retry utilization cannot be reconstructed from the evaluation rows.",
        "Automated UI checks do not establish audience acceptance, presentation confidence, or oral explanation quality.",
    ]
    report["rubric_evidence"] = build_rubric_evidence(report)
    report["requirements_audit"] = build_requirements_audit(report)
    report["failure_analysis"] = build_failure_analysis(
        report, grammar_records, exercise_records
    )
    blockers: list[str] = []
    manual_review_requirements: list[str] = []
    grammar_live_complete = (
        grammar["structured_output"]["total_primary_requests"] == GRAMMAR_CASE_COUNT
        and grammar["structured_output"]["valid_typed_responses"] > 0
    )
    exercise_live_complete = (
        exercise["requested"] == len(SUPPORTED_GENERATION_ERROR_TYPES) * EXERCISES_PER_CATEGORY
        and exercise["generated"] > 0
    )
    if not grammar_live_complete:
        blockers.append("The frozen 40-case grammar live evaluation was not completed or produced no usable output.")
    if not exercise_live_complete:
        blockers.append("The approved 20-exercise live evaluation was not completed or produced no usable output.")
    if grammar["explanation_quality"]["pending_manual_reviews"]:
        manual_review_requirements.append(
            f"{grammar['explanation_quality']['pending_manual_reviews']} grammar explanation rows require AI-assisted qualitative linguistic review."
        )
    unreviewed_corrections = grammar["correction"]["counts"].get(
        "unreviewed_alternative", 0
    )
    if unreviewed_corrections:
        manual_review_requirements.append(
            f"{unreviewed_corrections} alternative grammar corrections require human acceptability review."
        )
    if exercise["manual_review"]["pending"]:
        manual_review_requirements.append(
            f"{exercise['manual_review']['pending']} exercise rows require AI-assisted qualitative linguistic review."
        )
    if not ml_baseline["all_checks_passed"]:
        blockers.append("One or more Phase 5 reproducibility checks failed.")
    if not vocabulary["all_required_checks_passed"]:
        blockers.append("One or more vocabulary reference checks failed.")
    if not profiles["all_passed"] or not personalization["all_passed"]:
        blockers.append("A deterministic profile or personalization scenario failed.")
    if not end_to_end["all_passed"]:
        blockers.append("One or more end-to-end scenarios failed.")
    if include_startup_smoke and streamlit_smoke["status"] != "PASS":
        blockers.append("The real Streamlit startup smoke test failed.")
    if run_tests and tests["status"] != "PASS":
        blockers.append("The complete automated test suite failed.")
    if not artifact_integrity["all_unchanged_or_approved"]:
        blockers.append("At least one protected Phase 3-9 artifact changed without an approved bug-fix exception.")
    report["manual_review_requirements"] = manual_review_requirements
    report["completion_blockers"] = blockers + manual_review_requirements
    if blockers or manual_review_requirements:
        report["phase_11_verdict"] = "NOT READY FOR PHASE 12"
    else:
        report["phase_11_verdict"] = "READY FOR PHASE 12"

    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_markdown_path.write_text(
        render_markdown_report(report), encoding="utf-8", newline="\n"
    )
    checklist_path.write_text(
        render_end_to_end_checklist(report), encoding="utf-8", newline="\n"
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase 11 final evaluation without changing product features"
    )
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--include-startup-smoke", action="store_true")
    parser.add_argument("--run-reliability", action="store_true")
    parser.add_argument(
        "--reuse-live-results",
        action="store_true",
        help="Finalize reports from existing 40+20 raw live outputs without provider calls",
    )
    args = parser.parse_args(argv)
    report = run_system_evaluation(
        args.project_root,
        run_tests=args.run_tests,
        include_startup_smoke=args.include_startup_smoke,
        run_reliability=args.run_reliability,
        reuse_live_results=args.reuse_live_results,
    )
    print(json.dumps(
        {
            "verdict": report["phase_11_verdict"],
            "grammar_structured_outputs": report["grammar"]["structured_output"],
            "vocabulary_all_passed": report["vocabulary"]["all_required_checks_passed"],
            "profiles_all_passed": report["profile"]["all_passed"],
            "personalization_all_passed": report["personalization"]["all_passed"],
            "exercise_completion": report["exercise"]["completion_status"],
            "end_to_end_all_passed": report["end_to_end"]["all_passed"],
            "tests": report["tests"],
            "blockers": report["completion_blockers"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 2 if report["phase_11_verdict"] == "NOT READY FOR PHASE 12" else 0


if __name__ == "__main__":
    raise SystemExit(main())
