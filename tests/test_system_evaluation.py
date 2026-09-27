"""Focused checks for reusable Phase 11 evaluation logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation.system_evaluation import (
    EXERCISES_PER_CATEGORY,
    GRAMMAR_CASE_COUNT,
    VOCABULARY_CASE_COUNT,
    aggregate_exercise_results,
    aggregate_grammar_results,
    evaluate_personalization,
    evaluate_profiles,
    evaluate_vocabulary,
    load_jsonl,
    merge_qualitative_reviews,
    verify_ml_baseline,
    vocabulary_index_statistics,
    write_manual_review_worksheets,
)
from app.models.exercise import SUPPORTED_GENERATION_ERROR_TYPES
from app.services.ml_training import load_pipeline
from app.services.vocabulary_service import VocabularyService


ROOT = Path(__file__).resolve().parents[1]


def _grammar_record(
    case_id: str,
    *,
    expected_correct: bool,
    predicted_correct: bool,
    expected_categories: list[str],
    predicted_categories: list[str],
) -> dict:
    return {
        "case_id": case_id,
        "run_status": "success",
        "structured_output_valid": True,
        "expected": {
            "is_correct": expected_correct,
            "analysis_status": "COMPLETE",
            "error_types": expected_categories,
            "acceptable_corrections": ["accepted"],
        },
        "result": {
            "is_correct": predicted_correct,
            "analysis_status": "COMPLETE",
        },
        "score": {
            "expected_categories": expected_categories,
            "predicted_categories": predicted_categories,
            "category_precision": (
                len(set(expected_categories) & set(predicted_categories))
                / len(predicted_categories)
                if predicted_categories
                else 0.0
            ),
            "category_recall": (
                len(set(expected_categories) & set(predicted_categories))
                / len(expected_categories)
                if expected_categories
                else 1.0
            ),
            "category_f1": None,
            "category_exact_match": set(expected_categories) == set(predicted_categories),
            "correction_outcome": "exact_match",
            "failure_reasons": [],
        },
        "manual_explanation_review": {"status": "COMPLETED", "reviewer": "test"},
    }


def test_frozen_evaluation_dataset_sizes_and_unique_ids() -> None:
    grammar = load_jsonl(ROOT / "data" / "evaluation" / "grammar_cases_v1.jsonl")
    vocabulary = load_jsonl(ROOT / "data" / "evaluation" / "vocabulary_cases_v1.jsonl")
    assert len(grammar) == GRAMMAR_CASE_COUNT
    assert len(vocabulary) == VOCABULARY_CASE_COUNT
    assert len({case["case_id"] for case in grammar}) == len(grammar)
    assert len({case["case_id"] for case in vocabulary}) == len(vocabulary)


def test_grammar_detection_and_false_positive_metrics_use_only_actual_predictions() -> None:
    cases = [
        {"case_id": "correct_1", "expected_is_correct": True, "expected_error_types": [], "expected_analysis_status": "COMPLETE"},
        {"case_id": "correct_2", "expected_is_correct": True, "expected_error_types": [], "expected_analysis_status": "COMPLETE"},
        {"case_id": "single_case_1", "expected_is_correct": False, "expected_error_types": ["CASE_ERROR"], "expected_analysis_status": "COMPLETE"},
        {"case_id": "single_verb_1", "expected_is_correct": False, "expected_error_types": ["VERB_CONJUGATION"], "expected_analysis_status": "COMPLETE"},
    ]
    records = [
        _grammar_record("correct_1", expected_correct=True, predicted_correct=True, expected_categories=[], predicted_categories=[]),
        _grammar_record("correct_2", expected_correct=True, predicted_correct=False, expected_categories=[], predicted_categories=["OTHER"]),
        _grammar_record("single_case_1", expected_correct=False, predicted_correct=False, expected_categories=["CASE_ERROR"], predicted_categories=["CASE_ERROR"]),
        _grammar_record("single_verb_1", expected_correct=False, predicted_correct=True, expected_categories=["VERB_CONJUGATION"], predicted_categories=[]),
    ]
    metrics = aggregate_grammar_results(records, cases)
    assert metrics["detection"]["accuracy"] == pytest.approx(0.5)
    assert metrics["detection"]["precision"] == pytest.approx(0.5)
    assert metrics["detection"]["recall"] == pytest.approx(0.5)
    assert metrics["detection"]["f1"] == pytest.approx(0.5)
    assert metrics["false_positive_rate"]["false_positives"] == 1
    assert metrics["false_positive_rate"]["evaluated_valid_sentences"] == 2
    assert metrics["false_positive_rate"]["rate"] == pytest.approx(0.5)


def test_correct_sentence_correction_is_not_applicable() -> None:
    cases = [
        {
            "case_id": "correct_1",
            "expected_is_correct": True,
            "expected_error_types": [],
            "expected_analysis_status": "COMPLETE",
        }
    ]
    record = _grammar_record(
        "correct_1",
        expected_correct=True,
        predicted_correct=True,
        expected_categories=[],
        predicted_categories=[],
    )
    record["score"]["correction_outcome"] = "not_applicable"
    correction = aggregate_grammar_results([record], cases)["correction"]
    assert correction["evaluated_outputs"] == 0
    assert correction["not_applicable"] == 1
    assert correction["no_output"] == 0
    assert correction["exact_match_rate"] is None


def test_correction_aggregation_keeps_no_output_separate() -> None:
    cases = [
        {
            "case_id": "uncertain_1",
            "expected_is_correct": True,
            "expected_error_types": [],
            "expected_analysis_status": "UNCERTAIN",
        }
    ]
    record = {
        "case_id": "uncertain_1",
        "run_status": "controlled_failure",
        "failure_reason": "invalid_provider_output",
        "expected": {"is_correct": True, "error_types": []},
        "manual_explanation_review": {"status": "NOT_REVIEWABLE_NO_OUTPUT"},
    }
    correction = aggregate_grammar_results([record], cases)["correction"]
    assert correction["evaluated_outputs"] == 0
    assert correction["not_applicable"] == 0
    assert correction["no_output"] == 1
    assert correction["counts"]["no_output"] == 1


def test_missed_error_with_unchanged_sentence_is_incorrect_correction() -> None:
    from app.evaluation.system_evaluation import _score_grammar_success
    from app.models.grammar import GrammarResult

    case = {
        "sentence": "He on kotona.",
        "expected_is_correct": False,
        "expected_analysis_status": "COMPLETE",
        "expected_error_types": ["VERB_CONJUGATION"],
        "acceptable_corrections": ["He ovat kotona."],
    }
    result = GrammarResult.from_dict(
        {
            "schema_version": "1.0",
            "original_sentence": "He on kotona.",
            "language_mode": "STANDARD",
            "analysis_status": "COMPLETE",
            "is_correct": True,
            "corrected_sentence": "He on kotona.",
            "errors": [],
            "overall_explanation": "The sentence is correct.",
            "learning_tip": "Check subject-verb agreement.",
            "uncertainty_note": None,
        },
        expected_original="He on kotona.",
    )
    score = _score_grammar_success(case, result, None)
    assert score["correction_outcome"] == "incorrect_correction"


def test_multiple_error_metrics_are_set_based() -> None:
    cases = [
        {
            "case_id": "multiple_1",
            "expected_is_correct": False,
            "expected_error_types": ["CASE_ERROR", "VERB_CONJUGATION"],
            "expected_analysis_status": "COMPLETE",
        }
    ]
    record = _grammar_record(
        "multiple_1",
        expected_correct=False,
        predicted_correct=False,
        expected_categories=["CASE_ERROR", "VERB_CONJUGATION"],
        predicted_categories=["VERB_CONJUGATION", "WORD_ORDER"],
    )
    record["score"]["category_precision"] = 0.5
    record["score"]["category_recall"] = 0.5
    record["score"]["category_f1"] = 0.5
    metrics = aggregate_grammar_results([record], cases)["multiple_error_category"]
    assert metrics["micro_precision"] == pytest.approx(0.5)
    assert metrics["micro_recall"] == pytest.approx(0.5)
    assert metrics["micro_f1"] == pytest.approx(0.5)
    assert metrics["set_exact_match_rate"] == 0.0


def test_actual_vocabulary_reference_set_and_index_statistics_pass() -> None:
    service = VocabularyService(ROOT / "data" / "vocabulary" / "vocabulary_index_v1.jsonl")
    cases = load_jsonl(ROOT / "data" / "evaluation" / "vocabulary_cases_v1.jsonl")
    result = evaluate_vocabulary(service, cases)
    assert result["all_required_checks_passed"] is True
    assert all(value["passed"] == value["evaluated"] for value in result["metrics"].values())
    statistics = vocabulary_index_statistics(
        ROOT / "data" / "vocabulary" / "vocabulary_index_v1.jsonl",
        ROOT / "data" / "vocabulary" / "vocabulary_manifest_v1.json",
    )
    assert statistics["manifest_hash_matches"] is True
    assert statistics["ambiguous_lookup_keys"] > 0


def test_controlled_profile_and_personalization_evaluations_pass() -> None:
    profiles = evaluate_profiles()
    personalization = evaluate_personalization()
    assert profiles["scenario_count"] == 6
    assert profiles["all_passed"] is True
    assert personalization["profile_count"] == 4
    assert personalization["all_passed"] is True


def test_exercise_aggregation_keeps_provider_failures_visible() -> None:
    records = [
        {
            "target_error_type": category.value,
            "run_status": "controlled_failure",
            "structurally_valid": False,
            "failure_reason": "provider_configuration_failure",
            "latency_ms": 0.1,
            "manual_linguistic_review": {"status": "NOT_REVIEWABLE_NO_OUTPUT"},
        }
        for category in SUPPORTED_GENERATION_ERROR_TYPES
        for _ in range(EXERCISES_PER_CATEGORY)
    ]
    result = aggregate_exercise_results(records)
    assert result["requested"] == 20
    assert result["generated"] == 0
    assert result["schema_valid"] == 0
    assert result["provider_failures"] == 20
    assert result["structural_validity_rate_over_all_requests"] == 0.0
    assert result["completion_status"] == "BLOCKED_OR_INCOMPLETE"


def test_manual_review_worksheets_leave_subjective_fields_pending(tmp_path: Path) -> None:
    grammar_path = tmp_path / "grammar.jsonl"
    exercise_path = tmp_path / "exercise.jsonl"
    grammar_record = _grammar_record(
        "single_case_1",
        expected_correct=False,
        predicted_correct=False,
        expected_categories=["CASE_ERROR"],
        predicted_categories=["CASE_ERROR"],
    )
    grammar_record["sentence"] = "Pidän kahvi."
    grammar_record["result"].update(
        {
            "corrected_sentence": "Pidän kahvista.",
            "errors": [{"explanation": "The verb requires elative."}],
            "overall_explanation": "Case government.",
            "learning_tip": "Learn verbs with their governed case.",
        }
    )
    exercise_record = {
        "request_id": "case_error_01",
        "target_error_type": "CASE_ERROR",
        "exercise_type": "MULTIPLE_CHOICE",
        "difficulty": "BASIC",
        "run_status": "success",
        "schema_valid": True,
        "structurally_valid": True,
        "structural_checks": {"typed_schema_valid": True},
        "exercise": {
            "exercise_id": "sha256:test",
            "question": "Valitse oikea muoto.",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
            "explanation": "A is correct.",
        },
    }
    write_manual_review_worksheets(
        grammar_path, exercise_path, [grammar_record], [exercise_record]
    )
    grammar_review = load_jsonl(grammar_path)[0]
    exercise_review = load_jsonl(exercise_path)[0]
    assert grammar_review["status"] == "PENDING_MANUAL_REVIEW"
    assert grammar_review["grammatical_correctness"] is None
    assert exercise_review["status"] == "PENDING_MANUAL_REVIEW"
    assert exercise_review["answer_correctness"] is None


def test_completed_qualitative_reviews_merge_and_survive_worksheet_render(
    tmp_path: Path,
) -> None:
    grammar_record = _grammar_record(
        "single_case_1",
        expected_correct=False,
        predicted_correct=False,
        expected_categories=["CASE_ERROR"],
        predicted_categories=["CASE_ERROR"],
    )
    grammar_record["sentence"] = "Pidän kahvi."
    grammar_record["result"].update(
        {
            "corrected_sentence": "Pidän kahvista.",
            "errors": [{"explanation": "The verb requires elative."}],
            "overall_explanation": "Case government.",
            "learning_tip": "Learn verbs with their governed case.",
        }
    )
    exercise_record = {
        "request_id": "case_error_01",
        "target_error_type": "CASE_ERROR",
        "exercise_type": "MULTIPLE_CHOICE",
        "difficulty": "BASIC",
        "run_status": "success",
        "schema_valid": True,
        "structurally_valid": True,
        "structural_checks": {"typed_schema_valid": True},
        "latency_ms": 1.0,
        "exercise": {
            "exercise_id": "sha256:test",
            "question": "Valitse oikea muoto.",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
            "explanation": "A is correct.",
        },
        "manual_linguistic_review": {"status": "PENDING_MANUAL_REVIEW"},
    }
    grammar_review = {
        "case_id": "single_case_1",
        "status": "COMPLETED",
        "reviewer": "reviewer",
        "review_method": "AI-assisted qualitative linguistic review",
        "scale": "1-3",
        "grammatical_correctness": 2,
        "relevance": 3,
        "clarity": 3,
        "learner_usefulness": 2,
        "correction_acceptability": None,
        "notes": "Minor terminology issue.",
    }
    exercise_review = {
        "exercise_id": "case_error_01",
        "status": "COMPLETED",
        "reviewer": "reviewer",
        "review_method": "AI-assisted qualitative linguistic review",
        "scale": "PASS/PARTIAL/FAIL",
        "target_relevance": "PASS",
        "question_clarity": "PASS",
        "unambiguous": "PASS",
        "answer_correctness": "PASS",
        "distractor_plausibility": "PARTIAL",
        "explanation_correctness": "PASS",
        "no_unrelated_errors": "PASS",
        "failure_reasons": ["weak_distractor"],
        "notes": "One distractor is weak.",
    }
    original_result = dict(grammar_record["result"])
    merged_grammar, merged_exercises = merge_qualitative_reviews(
        [grammar_record],
        [exercise_record],
        {"single_case_1": grammar_review},
        {"case_error_01": exercise_review},
    )
    assert grammar_record["result"] == original_result
    assert merged_grammar[0]["result"] == original_result
    assert merged_grammar[0]["manual_explanation_review"]["status"] == "COMPLETED"
    assert merged_exercises[0]["manual_linguistic_review"]["distractor_plausibility"] == "PARTIAL"

    grammar_path = tmp_path / "grammar.jsonl"
    exercise_path = tmp_path / "exercise.jsonl"
    write_manual_review_worksheets(
        grammar_path,
        exercise_path,
        merged_grammar,
        merged_exercises,
    )
    assert load_jsonl(grammar_path)[0]["grammatical_correctness"] == 2
    assert load_jsonl(exercise_path)[0]["failure_reasons"] == ["weak_distractor"]

    cases = [
        {
            "case_id": "single_case_1",
            "expected_is_correct": False,
            "expected_error_types": ["CASE_ERROR"],
            "expected_analysis_status": "COMPLETE",
        }
    ]
    grammar_summary = aggregate_grammar_results(merged_grammar, cases)[
        "explanation_quality"
    ]["criterion_summary"]
    assert grammar_summary["grammatical_correctness"]["score_2"] == 1
    exercise_summary = aggregate_exercise_results(merged_exercises)["manual_review"][
        "criterion_summary"
    ]
    assert exercise_summary["distractor_plausibility"]["non_pass_rate"] == 1.0


def test_frozen_phase5_pipeline_loads_from_evaluation_entrypoint() -> None:
    pipeline = load_pipeline(ROOT / "models" / "error_classifier_v1.joblib")
    assert pipeline.predict(["Minä menee kouluun."])[0] in {
        "AGREEMENT",
        "CASE_ERROR",
        "VERB_CONJUGATION",
    }


def test_phase5_reproducibility_verification_passes() -> None:
    result = verify_ml_baseline(ROOT)
    assert result["all_checks_passed"] is True
    assert result["split_identity"]["actual_group_intersections"] == {
        "train_validation": 0,
        "train_test": 0,
        "validation_test": 0,
    }
