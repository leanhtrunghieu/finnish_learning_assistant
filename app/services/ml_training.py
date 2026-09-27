"""Leakage-safe Phase 5 baseline training for synthetic Finnish errors."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import unicodedata
import warnings
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import joblib
import numpy as np
import sklearn
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    log_loss,
    precision_recall_fscore_support,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline


MODEL_VERSION = "v1"
SCHEMA_VERSION = "1.0"
APPROVED_LABELS = ("AGREEMENT", "CASE_ERROR", "VERB_CONJUGATION")
SPLIT_NAMES = ("train", "validation", "test")
REQUIRED_FIELDS = {
    "synthetic_id",
    "source_id",
    "leakage_group_id",
    "source_dataset",
    "incorrect_sentence",
    "error_type",
}


class MLTrainingError(ValueError):
    """Raised when Phase 5 input or an experiment invariant is invalid."""


@dataclass(frozen=True)
class MLConfig:
    random_seed: int = 42
    n_splits: int = 20
    train_folds: int = 14
    validation_folds: int = 3
    test_folds: int = 3
    analyzer: str = "char_wb"
    ngram_min: int = 3
    ngram_max: int = 5
    min_df: int = 2
    max_features: int = 50_000
    sublinear_tf: bool = True
    lowercase: bool = True
    logistic_c: float = 1.0
    solver: str = "lbfgs"
    max_iter: int = 2_000
    class_weight: str | None = None

    def __post_init__(self) -> None:
        if self.n_splits < 3:
            raise MLTrainingError("n_splits must be at least 3")
        if self.train_folds + self.validation_folds + self.test_folds != self.n_splits:
            raise MLTrainingError("train/validation/test fold counts must sum to n_splits")
        if min(self.train_folds, self.validation_folds, self.test_folds) < 1:
            raise MLTrainingError("every split must receive at least one fold")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_versions() -> dict[str, str]:
    """Return the library versions needed to reproduce and load the artifact."""
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }


def _json_dump(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl_dump(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def normalize_feature_text(text: str) -> str:
    """Normalize only formatting noise in the model view, never stored source text."""
    if not isinstance(text, str) or not text.strip():
        raise MLTrainingError("prediction text must be a non-empty string")
    normalized = unicodedata.normalize("NFC", text)
    normalized = re.sub(r"\s+", " ", normalized.strip())
    return re.sub(r"\s+([,.;:!?])", r"\1", normalized)


class FinnishTextNormalizer(BaseEstimator, TransformerMixin):
    """Pickle-safe scikit-learn transformer for the documented feature view."""

    def fit(self, X: Sequence[str], y: Sequence[str] | None = None) -> "FinnishTextNormalizer":
        return self

    def transform(self, X: Sequence[str]) -> list[str]:
        return [normalize_feature_text(text) for text in X]


def load_synthetic_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MLTrainingError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            missing = sorted(REQUIRED_FIELDS - record.keys())
            if missing:
                raise MLTrainingError(f"{path}:{line_number}: missing fields: {', '.join(missing)}")
            if record["error_type"] not in APPROVED_LABELS:
                raise MLTrainingError(f"{path}:{line_number}: unapproved label {record['error_type']!r}")
            if record["synthetic_id"] in seen_ids:
                raise MLTrainingError(f"{path}:{line_number}: duplicate synthetic_id")
            normalize_feature_text(record["incorrect_sentence"])
            seen_ids.add(record["synthetic_id"])
            records.append(record)
    if not records:
        raise MLTrainingError(f"{path}: no records")
    if set(record["error_type"] for record in records) != set(APPROVED_LABELS):
        raise MLTrainingError("input does not contain exactly the approved Phase 4 labels")
    return records


def split_records(
    records: Sequence[Mapping[str, Any]], config: MLConfig = MLConfig()
) -> tuple[dict[str, list[Mapping[str, Any]]], list[int]]:
    """Assign grouped, composite-stratified folds and aggregate them into 70/15/15 splits."""
    strata = [f"{row['error_type']}|{row['source_dataset']}" for row in records]
    groups = [str(row["leakage_group_id"]) for row in records]
    fold_by_index = [-1] * len(records)
    splitter = StratifiedGroupKFold(
        n_splits=config.n_splits, shuffle=True, random_state=config.random_seed
    )
    dummy_x = np.zeros(len(records), dtype=np.uint8)
    for fold, (_, test_indices) in enumerate(splitter.split(dummy_x, strata, groups)):
        for index in test_indices:
            fold_by_index[int(index)] = fold
    if any(fold < 0 for fold in fold_by_index):
        raise MLTrainingError("group splitter did not assign every record")

    train_end = config.train_folds
    validation_end = train_end + config.validation_folds
    split_rows: dict[str, list[Mapping[str, Any]]] = {name: [] for name in SPLIT_NAMES}
    for row, fold in zip(records, fold_by_index):
        name = "train" if fold < train_end else "validation" if fold < validation_end else "test"
        split_rows[name].append(row)
    verify_group_isolation(split_rows)
    return split_rows, fold_by_index


def verify_group_isolation(splits: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    groups = {
        name: {str(row["leakage_group_id"]) for row in splits[name]} for name in SPLIT_NAMES
    }
    intersections = {
        "train_validation": sorted(groups["train"] & groups["validation"]),
        "train_test": sorted(groups["train"] & groups["test"]),
        "validation_test": sorted(groups["validation"] & groups["test"]),
    }
    if any(intersections.values()):
        raise MLTrainingError(f"leakage-group overlap detected: {intersections}")
    return {
        "passed": True,
        "intersection_counts": {key: len(value) for key, value in intersections.items()},
        "intersections": intersections,
    }


def build_pipeline(config: MLConfig = MLConfig()) -> Pipeline:
    return Pipeline(
        [
            ("normalize", FinnishTextNormalizer()),
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer=config.analyzer,
                    ngram_range=(config.ngram_min, config.ngram_max),
                    min_df=config.min_df,
                    max_features=config.max_features,
                    sublinear_tf=config.sublinear_tf,
                    lowercase=config.lowercase,
                    strip_accents=None,
                    dtype=np.float64,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=config.logistic_c,
                    solver=config.solver,
                    max_iter=config.max_iter,
                    class_weight=config.class_weight,
                    random_state=config.random_seed,
                ),
            ),
        ]
    )


def fit_pipeline(pipeline: Pipeline, records: Sequence[Mapping[str, Any]]) -> None:
    texts = [str(row["incorrect_sentence"]) for row in records]
    labels = [str(row["error_type"]) for row in records]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        pipeline.fit(texts, labels)
    convergence = [warning for warning in caught if issubclass(warning.category, ConvergenceWarning)]
    if convergence:
        raise MLTrainingError(f"Logistic Regression did not converge: {convergence[0].message}")


def _metric_bundle(true: Sequence[str], predicted: Sequence[str], probabilities: np.ndarray) -> dict[str, Any]:
    precision, recall, f1, support = precision_recall_fscore_support(
        true, predicted, labels=list(APPROVED_LABELS), zero_division=0
    )
    macro = precision_recall_fscore_support(true, predicted, average="macro", zero_division=0)
    return {
        "accuracy": float(accuracy_score(true, predicted)),
        "macro_precision": float(macro[0]),
        "macro_recall": float(macro[1]),
        "macro_f1": float(macro[2]),
        "log_loss": float(log_loss(true, probabilities, labels=list(APPROVED_LABELS))),
        "per_class": {
            label: {
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(f1[index]),
                "support": int(support[index]),
            }
            for index, label in enumerate(APPROVED_LABELS)
        },
        "confusion_matrix": {
            "labels": list(APPROVED_LABELS),
            "values": confusion_matrix(true, predicted, labels=list(APPROVED_LABELS)).tolist(),
        },
    }


def evaluate_pipeline(pipeline: Pipeline, records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    texts = [str(row["incorrect_sentence"]) for row in records]
    true = [str(row["error_type"]) for row in records]
    predicted = pipeline.predict(texts).tolist()
    raw_probabilities = pipeline.predict_proba(texts)
    classifier_labels = pipeline.named_steps["classifier"].classes_.tolist()
    order = [classifier_labels.index(label) for label in APPROVED_LABELS]
    probabilities = raw_probabilities[:, order]
    metrics = _metric_bundle(true, predicted, probabilities)
    predictions = []
    for row, expected, actual, probs in zip(records, true, predicted, probabilities):
        predictions.append(
            {
                "synthetic_id": row["synthetic_id"],
                "source_id": row["source_id"],
                "leakage_group_id": row["leakage_group_id"],
                "source_dataset": row["source_dataset"],
                "incorrect_sentence": row["incorrect_sentence"],
                "true_label": expected,
                "predicted_label": actual,
                "confidence": float(max(probs)),
                "probabilities": {label: float(probs[i]) for i, label in enumerate(APPROVED_LABELS)},
                "correct": expected == actual,
            }
        )
    return metrics, predictions


def predict_error_type(pipeline: Pipeline, text: str) -> dict[str, Any]:
    normalize_feature_text(text)
    predicted = str(pipeline.predict([text])[0])
    raw = pipeline.predict_proba([text])[0]
    classes = pipeline.named_steps["classifier"].classes_.tolist()
    probabilities = {label: float(raw[classes.index(label)]) for label in APPROVED_LABELS}
    return {
        "predicted_error_type": predicted,
        "confidence": probabilities[predicted],
        "probabilities": probabilities,
    }


def inspect_features(pipeline: Pipeline, top_n: int = 20) -> dict[str, list[dict[str, Any]]]:
    features = pipeline.named_steps["tfidf"].get_feature_names_out()
    classifier = pipeline.named_steps["classifier"]
    result: dict[str, list[dict[str, Any]]] = {}
    for class_index, label in enumerate(classifier.classes_):
        indices = np.argsort(classifier.coef_[class_index])[-top_n:][::-1]
        result[str(label)] = [
            {"feature": str(features[index]), "weight": float(classifier.coef_[class_index, index])}
            for index in indices
        ]
    return result


def _counts(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[field]) for row in rows).items()))


def _source_metrics(pipeline: Pipeline, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output = {}
    for source in sorted({str(row["source_dataset"]) for row in rows}):
        subset = [row for row in rows if row["source_dataset"] == source]
        output[source] = evaluate_pipeline(pipeline, subset)[0]
    return output


def _source_only_baseline(
    train: Sequence[Mapping[str, Any]], evaluation: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    for row in train:
        by_source[str(row["source_dataset"])][str(row["error_type"])] += 1
    global_label = Counter(str(row["error_type"]) for row in train).most_common(1)[0][0]
    mapping = {
        source: sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for source, counts in by_source.items()
    }
    expected = [str(row["error_type"]) for row in evaluation]
    predicted = [mapping.get(str(row["source_dataset"]), global_label) for row in evaluation]
    return {"accuracy": float(accuracy_score(expected, predicted)), "source_to_label": mapping}


def _length_sensitivity(
    pipeline: Pipeline,
    train: Sequence[Mapping[str, Any]],
    evaluation: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate fixed train-derived sentence-length quartiles without test fitting."""
    train_lengths = np.array(
        [len(normalize_feature_text(str(row["incorrect_sentence"]))) for row in train], dtype=float
    )
    thresholds = np.quantile(train_lengths, [0.25, 0.5, 0.75]).tolist()
    names = ("Q1_shortest", "Q2", "Q3", "Q4_longest")
    buckets: dict[str, list[Mapping[str, Any]]] = {name: [] for name in names}
    for row in evaluation:
        length = len(normalize_feature_text(str(row["incorrect_sentence"])))
        index = int(np.searchsorted(thresholds, length, side="right"))
        buckets[names[index]].append(row)
    results = {}
    for name, rows in buckets.items():
        if not rows:
            results[name] = {"records": 0, "class_distribution": {}}
            continue
        bundle = evaluate_pipeline(pipeline, rows)[0]
        results[name] = {
            "records": len(rows),
            "class_distribution": _counts(rows, "error_type"),
            "accuracy": bundle["accuracy"],
            "macro_f1": bundle["macro_f1"],
        }
    return {"train_character_length_quartile_thresholds": thresholds, "evaluation": results}


def save_pipeline(pipeline: Pipeline, path: Path) -> None:
    # ``python -m app.services.ml_training`` executes this file as ``__main__``.
    # Give the custom transformer a stable import path before new artifacts are
    # serialized so they can be loaded from another entry point.
    stable_module = "app.services.ml_training"
    if FinnishTextNormalizer.__module__ == "__main__":
        sys.modules.setdefault(stable_module, sys.modules["__main__"])
        FinnishTextNormalizer.__module__ = stable_module
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, path)


def load_pipeline(path: Path) -> Pipeline:
    # Phase 5 v1 was created through ``python -m`` and therefore contains the
    # legacy pickle reference ``__main__.FinnishTextNormalizer``.  Expose only
    # this known project class while loading that frozen artifact; restore the
    # caller's module immediately afterwards.  The model bytes remain unchanged.
    main_module = sys.modules["__main__"]
    marker = object()
    previous = getattr(main_module, "FinnishTextNormalizer", marker)
    setattr(main_module, "FinnishTextNormalizer", FinnishTextNormalizer)
    try:
        pipeline = joblib.load(path)
    finally:
        if previous is marker:
            delattr(main_module, "FinnishTextNormalizer")
        else:
            setattr(main_module, "FinnishTextNormalizer", previous)
    if not isinstance(pipeline, Pipeline):
        raise MLTrainingError(f"{path} does not contain a scikit-learn Pipeline")
    return pipeline


def run_phase5(project_root: Path, config: MLConfig = MLConfig()) -> dict[str, Any]:
    root = project_root.resolve()
    input_path = root / "data/errors/synthetic_errors_v1.jsonl"
    phase4_manifest_path = root / "data/errors/error_generation_manifest_v1.json"
    phase4_manifest = json.loads(phase4_manifest_path.read_text(encoding="utf-8"))
    input_hash = sha256_file(input_path)
    expected_hash = phase4_manifest.get("output", {}).get("sha256")
    if input_hash != expected_hash:
        raise MLTrainingError(f"Phase 4 input hash mismatch: expected {expected_hash}, got {input_hash}")
    records = load_synthetic_records(input_path)
    splits, fold_by_index = split_records(records, config)

    evaluation_dir = root / "data/evaluation"
    split_paths = {name: evaluation_dir / f"{name}_v1.jsonl" for name in SPLIT_NAMES}
    for name, path in split_paths.items():
        _jsonl_dump(path, splits[name])
    leakage = verify_group_isolation(splits)
    split_manifest = {
        "schema_version": SCHEMA_VERSION,
        "split_version": MODEL_VERSION,
        "input": {
            "path": "data/errors/synthetic_errors_v1.jsonl",
            "sha256": input_hash,
            "phase4_manifest_path": "data/errors/error_generation_manifest_v1.json",
            "phase4_manifest_sha256": sha256_file(phase4_manifest_path),
        },
        "configuration": {
            "random_seed": config.random_seed,
            "algorithm": "StratifiedGroupKFold",
            "stratification_key": "error_type|source_dataset",
            "group_key": "leakage_group_id",
            "n_splits": config.n_splits,
            "fold_allocation": {
                "train": list(range(config.train_folds)),
                "validation": list(range(config.train_folds, config.train_folds + config.validation_folds)),
                "test": list(range(config.train_folds + config.validation_folds, config.n_splits)),
            },
        },
        "total_records": len(records),
        "splits": {
            name: {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "records": len(splits[name]),
                "proportion": len(splits[name]) / len(records),
                "leakage_groups": len({row["leakage_group_id"] for row in splits[name]}),
                "class_distribution": _counts(splits[name], "error_type"),
                "source_distribution": _counts(splits[name], "source_dataset"),
                "composite_distribution": dict(
                    sorted(Counter(f"{row['error_type']}|{row['source_dataset']}" for row in splits[name]).items())
                ),
            }
            for name, path in split_paths.items()
        },
        "quality_checks": {
            "all_records_assigned_once": sum(len(rows) for rows in splits.values()) == len(records),
            "all_synthetic_ids_unique_across_splits": len({row["synthetic_id"] for rows in splits.values() for row in rows}) == len(records),
            "leakage_group_isolation": leakage,
        },
        "fold_assignment_sha256": hashlib.sha256(
            "\n".join(f"{row['synthetic_id']}:{fold}" for row, fold in zip(records, fold_by_index)).encode("utf-8")
        ).hexdigest(),
    }
    split_manifest_path = evaluation_dir / "ml_split_manifest_v1.json"
    _json_dump(split_manifest_path, split_manifest)

    pipeline = build_pipeline(config)
    fit_pipeline(pipeline, splits["train"])
    metrics: dict[str, Any] = {}
    prediction_rows: dict[str, list[dict[str, Any]]] = {}
    for name in SPLIT_NAMES:
        metrics[name], prediction_rows[name] = evaluate_pipeline(pipeline, splits[name])

    test_predictions_path = evaluation_dir / "ml_test_predictions_v1.jsonl"
    _jsonl_dump(test_predictions_path, prediction_rows["test"])
    model_path = root / "models/error_classifier_v1.joblib"
    save_pipeline(pipeline, model_path)
    loaded = load_pipeline(model_path)
    probe = str(splits["test"][0]["incorrect_sentence"])
    artifact_round_trip = predict_error_type(loaded, probe) == predict_error_type(pipeline, probe)

    misclassified = sorted(
        (row for row in prediction_rows["test"] if not row["correct"]),
        key=lambda row: (-row["confidence"], row["synthetic_id"]),
    )[:20]
    high_confidence: dict[str, list[dict[str, Any]]] = {}
    for label in APPROVED_LABELS:
        high_confidence[label] = sorted(
            (row for row in prediction_rows["test"] if row["correct"] and row["true_label"] == label),
            key=lambda row: (-row["confidence"], row["synthetic_id"]),
        )[:5]

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "prediction_task": {"input": "incorrect_sentence", "target": "error_type"},
        "input_dataset": {"path": "data/errors/synthetic_errors_v1.jsonl", "sha256": input_hash},
        "runtime_versions": runtime_versions(),
        "split_manifest": {
            "path": "data/evaluation/ml_split_manifest_v1.json",
            "sha256": sha256_file(split_manifest_path),
        },
        "configuration": asdict(config),
        "feature_configuration": {
            "normalization": "NFC; collapse whitespace; remove formatting-only spaces before ,.;:!? in feature view only",
            "vectorizer": "TfidfVectorizer",
            "analyzer": config.analyzer,
            "ngram_range": [config.ngram_min, config.ngram_max],
            "vocabulary_size": len(pipeline.named_steps["tfidf"].vocabulary_),
            "fit_scope": "training split only",
        },
        "classifier_configuration": {
            "type": "LogisticRegression",
            "C": config.logistic_c,
            "solver": config.solver,
            "max_iter": config.max_iter,
            "class_weight": config.class_weight,
            "random_state": config.random_seed,
            "iterations_by_class": pipeline.named_steps["classifier"].n_iter_.tolist(),
        },
        "labels": list(APPROVED_LABELS),
        "record_counts": {name: len(splits[name]) for name in SPLIT_NAMES},
        "metrics": metrics,
        "interpretation": {
            "top_positive_features": inspect_features(pipeline),
            "high_confidence_correct_test_examples": high_confidence,
            "misclassified_test_examples": misclassified,
        },
        "shortcut_checks": {
            "training_global_majority_accuracy": max(_counts(splits["train"], "error_type").values()) / len(splits["train"]),
            "validation_source_only_majority": _source_only_baseline(splits["train"], splits["validation"]),
            "test_source_only_majority": _source_only_baseline(splits["train"], splits["test"]),
            "validation_metrics_by_source": _source_metrics(pipeline, splits["validation"]),
            "test_metrics_by_source": _source_metrics(pipeline, splits["test"]),
            "validation_metrics_by_train_length_quartile": _length_sensitivity(
                pipeline, splits["train"], splits["validation"]
            ),
            "test_metrics_by_train_length_quartile": _length_sensitivity(
                pipeline, splits["train"], splits["test"]
            ),
            "train_test_macro_f1_gap": metrics["train"]["macro_f1"] - metrics["test"]["macro_f1"],
        },
        "artifacts": {
            "model": {"path": "models/error_classifier_v1.joblib", "sha256": sha256_file(model_path)},
            "test_predictions": {
                "path": "data/evaluation/ml_test_predictions_v1.jsonl",
                "sha256": sha256_file(test_predictions_path),
            },
        },
        "quality_checks": {
            "phase4_input_hash_verified": True,
            "group_overlap_zero": all(value == 0 for value in leakage["intersection_counts"].values()),
            "vectorizer_fit_on_training_only": True,
            "all_approved_labels_present_in_each_split": all(
                set(_counts(splits[name], "error_type")) == set(APPROVED_LABELS) for name in SPLIT_NAMES
            ),
            "classifier_converged": True,
            "artifact_load_and_prediction_verified": artifact_round_trip,
            "test_evaluated_after_fixed_configuration": True,
        },
        "limitations": [
            "This model classifies three controlled synthetic error types; it is not a detector of arbitrary real-world Finnish grammar errors.",
            "Character n-grams can learn generator-specific suffix and replacement artifacts rather than general grammar.",
            "Synthetic examples may not match the distribution or ambiguity of naturally occurring learner language.",
            "Reported log loss is post-fit classification log loss, not a neural-network training-loss curve.",
        ],
    }
    metadata_path = root / "models/error_classifier_v1_metadata.json"
    _json_dump(metadata_path, metadata)
    return metadata


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    metadata = run_phase5(args.project_root)
    print(json.dumps({"record_counts": metadata["record_counts"], "metrics": metadata["metrics"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
