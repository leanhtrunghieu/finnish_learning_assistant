import json
from pathlib import Path

import joblib
import pytest

from app.services.ml_training import (
    APPROVED_LABELS,
    MLConfig,
    MLTrainingError,
    build_pipeline,
    evaluate_pipeline,
    load_pipeline,
    load_synthetic_records,
    normalize_feature_text,
    predict_error_type,
    runtime_versions,
    save_pipeline,
    split_records,
    verify_group_isolation,
)


def _records() -> list[dict]:
    rows = []
    suffixes = {
        "AGREEMENT": "kauniit talo",
        "CASE_ERROR": "kauniissa talossa",
        "VERB_CONJUGATION": "minä ovat täällä",
    }
    index = 0
    for label in APPROVED_LABELS:
        for source in ("UD_Finnish-FTB", "UD_Finnish-TDT"):
            for number in range(8):
                index += 1
                rows.append(
                    {
                        "schema_version": "1.0",
                        "synthetic_id": f"synthetic-{index}",
                        "source_id": f"source-{index}",
                        "leakage_group_id": f"group-{index}",
                        "source_dataset": source,
                        "incorrect_sentence": f"Äiti sanoi: {suffixes[label]} {number}.",
                        "error_type": label,
                    }
                )
    return rows


@pytest.fixture
def small_config() -> MLConfig:
    return MLConfig(
        n_splits=4,
        train_folds=2,
        validation_folds=1,
        test_folds=1,
        min_df=1,
        max_features=2_000,
        max_iter=500,
    )


def test_group_split_is_deterministic_and_has_no_leakage(small_config: MLConfig) -> None:
    rows = _records()
    first, first_folds = split_records(rows, small_config)
    second, second_folds = split_records(rows, small_config)
    assert first_folds == second_folds
    assert {
        name: [row["synthetic_id"] for row in records] for name, records in first.items()
    } == {
        name: [row["synthetic_id"] for row in records] for name, records in second.items()
    }
    assert verify_group_isolation(first)["intersection_counts"] == {
        "train_validation": 0,
        "train_test": 0,
        "validation_test": 0,
    }
    assert sum(len(records) for records in first.values()) == len(rows)


def test_group_members_cannot_cross_splits(small_config: MLConfig) -> None:
    rows = _records()
    rows[1]["leakage_group_id"] = rows[0]["leakage_group_id"]
    splits, _ = split_records(rows, small_config)
    containing = [
        name
        for name, records in splits.items()
        if any(row["leakage_group_id"] == rows[0]["leakage_group_id"] for row in records)
    ]
    assert len(containing) == 1


def test_feature_normalization_preserves_finnish_content_and_punctuation() -> None:
    assert normalize_feature_text("  Äiti\t sanoi :  yö, hyvä!  ") == "Äiti sanoi: yö, hyvä!"
    assert normalize_feature_text("ÖLJY ääkkönen.") == "ÖLJY ääkkönen."
    with pytest.raises(MLTrainingError, match="non-empty"):
        normalize_feature_text("   ")


def test_vectorizer_is_fitted_only_on_supplied_training_text(small_config: MLConfig) -> None:
    rows = _records()
    pipeline = build_pipeline(small_config)
    pipeline.fit(
        [row["incorrect_sentence"] for row in rows],
        [row["error_type"] for row in rows],
    )
    vocabulary = pipeline.named_steps["tfidf"].vocabulary_
    assert " xyz" not in vocabulary
    pipeline.predict(["Täysin uusi XYZ-sana ei kaada mallia."])


def test_pipeline_predictions_probabilities_and_metrics(small_config: MLConfig) -> None:
    rows = _records()
    pipeline = build_pipeline(small_config)
    pipeline.fit([row["incorrect_sentence"] for row in rows], [row["error_type"] for row in rows])
    result = predict_error_type(pipeline, "Minä ovat täällä.")
    assert result["predicted_error_type"] in APPROVED_LABELS
    assert set(result["probabilities"]) == set(APPROVED_LABELS)
    assert sum(result["probabilities"].values()) == pytest.approx(1.0)
    metrics, predictions = evaluate_pipeline(pipeline, rows)
    assert set(metrics["per_class"]) == set(APPROVED_LABELS)
    assert len(metrics["confusion_matrix"]["values"]) == 3
    assert len(predictions) == len(rows)


def test_complete_pipeline_artifact_round_trip(tmp_path: Path, small_config: MLConfig) -> None:
    rows = _records()
    pipeline = build_pipeline(small_config)
    pipeline.fit([row["incorrect_sentence"] for row in rows], [row["error_type"] for row in rows])
    path = tmp_path / "model.joblib"
    save_pipeline(pipeline, path)
    loaded = load_pipeline(path)
    sentence = "Hän ovat kotona."
    assert predict_error_type(loaded, sentence) == predict_error_type(pipeline, sentence)


def test_invalid_artifact_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "invalid.joblib"
    joblib.dump({"not": "a pipeline"}, path)
    with pytest.raises(MLTrainingError, match="Pipeline"):
        load_pipeline(path)


def test_input_validation_rejects_bad_label_and_duplicate_id(tmp_path: Path) -> None:
    rows = _records()
    bad_label = tmp_path / "bad-label.jsonl"
    changed = [dict(row) for row in rows]
    changed[0]["error_type"] = "SPELLING"
    bad_label.write_text("\n".join(json.dumps(row) for row in changed), encoding="utf-8")
    with pytest.raises(MLTrainingError, match="unapproved"):
        load_synthetic_records(bad_label)

    duplicate = tmp_path / "duplicate.jsonl"
    changed = [dict(row) for row in rows]
    changed[1]["synthetic_id"] = changed[0]["synthetic_id"]
    duplicate.write_text("\n".join(json.dumps(row) for row in changed), encoding="utf-8")
    with pytest.raises(MLTrainingError, match="duplicate synthetic_id"):
        load_synthetic_records(duplicate)


def test_config_rejects_invalid_fold_allocation() -> None:
    with pytest.raises(MLTrainingError, match="sum"):
        MLConfig(n_splits=5, train_folds=3, validation_folds=1, test_folds=2)


def test_runtime_versions_are_recordable() -> None:
    versions = runtime_versions()
    assert set(versions) == {"python", "numpy", "scikit_learn", "joblib"}
    assert all(isinstance(value, str) and value for value in versions.values())
