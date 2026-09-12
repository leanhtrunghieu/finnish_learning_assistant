"""Controlled synthetic Finnish learner-error generation.

All replacements are observed in the Phase 3 corpus with the claimed
morphological analysis. The generator changes one aligned token span, retains
source/leakage provenance, and does not perform ML splitting or training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
GENERATOR_VERSION = "v1"

CASE_ERROR = "CASE_ERROR"
VERB_CONJUGATION = "VERB_CONJUGATION"
AGREEMENT = "AGREEMENT"
ERROR_TYPES = (CASE_ERROR, VERB_CONJUGATION, AGREEMENT)

CASE_RULE = "adjective_case_mismatch_v1"
VERB_RULE = "finite_verb_person_number_mismatch_v1"
AGREEMENT_RULE = "adjective_number_agreement_mismatch_v1"
RULE_TO_ERROR = {
    CASE_RULE: CASE_ERROR,
    VERB_RULE: VERB_CONJUGATION,
    AGREEMENT_RULE: AGREEMENT,
}
RULE_DESCRIPTIONS = {
    CASE_RULE: (
        "Replace an agreeing adjectival modifier with a corpus-attested form "
        "of the same lemma and number but a different case."
    ),
    VERB_RULE: (
        "Replace a finite active indicative verb with a corpus-attested form "
        "of the same lemma whose person/number conflicts with its overt pronoun subject."
    ),
    AGREEMENT_RULE: (
        "Replace an agreeing adjectival modifier with a corpus-attested form "
        "of the same lemma and case but the opposite number."
    ),
}

PHASE3_REQUIRED_FIELDS = {
    "schema_version",
    "source_dataset",
    "source_commit",
    "source_split",
    "source_file",
    "source_sentence_id",
    "source_id",
    "leakage_group_id",
    "original_text",
    "word_count",
    "empty_node_count",
    "multiword_tokens",
    "tokens",
}
SYNTHETIC_REQUIRED_FIELDS = {
    "schema_version",
    "synthetic_id",
    "source_id",
    "leakage_group_id",
    "source_dataset",
    "source_commit",
    "source_split",
    "source_file",
    "source_sentence_id",
    "correct_sentence",
    "incorrect_sentence",
    "error_type",
    "error_span",
    "correction",
    "generation_rule",
    "changed_token_id",
    "metadata",
}
PERSONAL_PRONOUNS = {
    "minä": ("1", "Sing"),
    "sinä": ("2", "Sing"),
    "hän": ("3", "Sing"),
    "me": ("1", "Plur"),
    "te": ("2", "Plur"),
    "he": ("3", "Plur"),
}
NOISY_FEATURES = {"Style", "Typo", "Foreign", "Abbr"}
SAFE_ADJECTIVE_FEATURES = {"Case", "Number", "Degree", "Derivation"}


class ErrorGenerationError(ValueError):
    """Invalid Phase 3 input, configuration, or generated example."""


class SpanAlignmentError(ErrorGenerationError):
    """A token sequence cannot be aligned exactly to the source text."""


@dataclass(frozen=True)
class GenerationConfig:
    """Deterministic sampling and safety configuration."""

    random_seed: int = 42
    maximum_examples_per_class: int = 1000
    minimum_examples_per_class: int = 500
    maximum_variants_per_leakage_group: int = 2
    maximum_examples_per_lemma_per_class: int = 50
    minimum_sentence_words: int = 3
    maximum_sentence_words: int = 30
    manual_review_examples_per_class: int = 20

    def validate(self) -> None:
        numeric_values = asdict(self)
        if any(not isinstance(value, int) for value in numeric_values.values()):
            raise ErrorGenerationError("all generation configuration values must be integers")
        if self.maximum_examples_per_class < 1:
            raise ErrorGenerationError("maximum_examples_per_class must be positive")
        if not 1 <= self.minimum_examples_per_class <= self.maximum_examples_per_class:
            raise ErrorGenerationError(
                "minimum_examples_per_class must be between 1 and maximum_examples_per_class"
            )
        if self.maximum_variants_per_leakage_group < 1:
            raise ErrorGenerationError("maximum_variants_per_leakage_group must be positive")
        if self.maximum_examples_per_lemma_per_class < 1:
            raise ErrorGenerationError("maximum_examples_per_lemma_per_class must be positive")
        if not 1 <= self.minimum_sentence_words <= self.maximum_sentence_words:
            raise ErrorGenerationError("sentence word limits are invalid")
        if self.manual_review_examples_per_class < 1:
            raise ErrorGenerationError("manual_review_examples_per_class must be positive")


@dataclass(frozen=True)
class FormObservation:
    """One deterministic corpus-attested replacement option."""

    grammatical_value: str | tuple[str, str]
    evidence_form: str
    evidence_count: int
    feats: dict[str, str]


@dataclass(frozen=True)
class Candidate:
    """One validated, pre-sampling single-token error candidate."""

    record: Mapping[str, Any]
    token_id: int
    lemma: str
    replacement_form: str
    replacement_feats: dict[str, str]
    evidence_form: str
    evidence_count: int
    error_type: str
    generation_rule: str
    feature_changes: dict[str, dict[str, str]]
    anchor_token_id: int
    correct_start: int
    correct_end: int


@dataclass
class FormIndexes:
    """Corpus-observed paradigms keyed by non-target morphology."""

    verbs: dict[tuple[Any, ...], dict[tuple[str, str], Counter[str]]]
    adjective_cases: dict[tuple[Any, ...], dict[str, Counter[str]]]
    adjective_numbers: dict[tuple[Any, ...], dict[str, Counter[str]]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_phase3_record(record: Mapping[str, Any], line_number: int) -> None:
    missing = PHASE3_REQUIRED_FIELDS - set(record)
    if missing:
        raise ErrorGenerationError(
            f"Phase 3 JSONL line {line_number} is missing fields: {sorted(missing)}"
        )
    if record["schema_version"] != "1.0":
        raise ErrorGenerationError(
            f"unsupported Phase 3 schema on line {line_number}: {record['schema_version']!r}"
        )
    if not isinstance(record["tokens"], list) or record["word_count"] != len(record["tokens"]):
        raise ErrorGenerationError(f"Phase 3 token count mismatch on line {line_number}")
    if not all(record.get(field) for field in ("source_id", "leakage_group_id", "original_text")):
        raise ErrorGenerationError(f"Phase 3 provenance/text is missing on line {line_number}")


def load_phase3_data(
    processed_path: Path,
    preprocessing_manifest_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
    """Load Phase 3 only after verifying its manifest and output hash."""

    try:
        preprocessing_manifest_bytes = preprocessing_manifest_path.read_bytes()
        preprocessing_manifest = json.loads(preprocessing_manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ErrorGenerationError(
            f"cannot read Phase 3 preprocessing manifest {preprocessing_manifest_path}: {exc}"
        ) from exc

    actual_input_hash = sha256_file(processed_path)
    expected_hash = preprocessing_manifest.get("output", {}).get("sha256")
    if actual_input_hash != expected_hash:
        raise ErrorGenerationError(
            f"Phase 3 JSONL hash mismatch: expected {expected_hash}, found {actual_input_hash}"
        )

    records: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    try:
        with processed_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ErrorGenerationError(
                        f"invalid JSON on Phase 3 JSONL line {line_number}: {exc}"
                    ) from exc
                _validate_phase3_record(record, line_number)
                source_id = record["source_id"]
                if source_id in source_ids:
                    raise ErrorGenerationError(f"duplicate Phase 3 source_id {source_id!r}")
                source_ids.add(source_id)
                records.append(record)
    except OSError as exc:
        raise ErrorGenerationError(f"cannot read Phase 3 JSONL {processed_path}: {exc}") from exc

    expected_sentences = preprocessing_manifest.get("output", {}).get("sentences")
    if len(records) != expected_sentences:
        raise ErrorGenerationError(
            f"Phase 3 sentence count mismatch: expected {expected_sentences}, found {len(records)}"
        )
    manifest_hash = hashlib.sha256(preprocessing_manifest_bytes).hexdigest()
    return records, preprocessing_manifest, actual_input_hash, manifest_hash


def align_token_spans(record: Mapping[str, Any]) -> dict[int, tuple[int, int]]:
    """Align normal tokens to original_text without normalizing its whitespace."""

    if record.get("multiword_tokens") or record.get("empty_nodes"):
        raise SpanAlignmentError("sentences with MWTs or empty nodes are excluded in generator v1")
    text = record["original_text"]
    tokens = record["tokens"]
    spans: dict[int, tuple[int, int]] = {}
    cursor = 0
    previous: Mapping[str, Any] | None = None
    for index, token in enumerate(tokens):
        if index == 0:
            start = cursor
            while start < len(text) and text[start].isspace():
                start += 1
        elif previous and previous.get("misc", {}).get("SpaceAfter") == "No":
            start = cursor
        else:
            start = cursor
            while start < len(text) and text[start].isspace():
                start += 1
        if not text.startswith(token["form"], start):
            raise SpanAlignmentError(
                f"cannot align token {token['id']} {token['form']!r} in {record['source_id']}"
            )
        if previous and previous.get("misc", {}).get("SpaceAfter") == "No" and start != cursor:
            raise SpanAlignmentError(
                f"unexpected whitespace before token {token['id']} in {record['source_id']}"
            )
        end = start + len(token["form"])
        spans[token["id"]] = (start, end)
        cursor = end
        previous = token
    if text[cursor:].strip():
        raise SpanAlignmentError(f"unmatched text remains in {record['source_id']}")
    return spans


def _has_noisy_features(feats: Mapping[str, str]) -> bool:
    return bool(NOISY_FEATURES.intersection(feats))


def _safe_verb(token: Mapping[str, Any]) -> bool:
    feats = token["feats"]
    return (
        token["upos"] in {"VERB", "AUX"}
        and bool(token.get("lemma"))
        and feats.get("VerbForm") == "Fin"
        and feats.get("Mood") == "Ind"
        and feats.get("Voice") == "Act"
        and feats.get("Person") in {"1", "2", "3"}
        and feats.get("Number") in {"Sing", "Plur"}
        and not _has_noisy_features(feats)
    )


def _safe_adjective(token: Mapping[str, Any]) -> bool:
    feats = token["feats"]
    return (
        token["upos"] == "ADJ"
        and token.get("lemma") is not None
        and token["deprel"] == "amod"
        and feats.get("Case") is not None
        and feats.get("Number") is not None
        # Finnish-FTB marks comparative/superlative degree explicitly but
        # legitimately omits Degree on positive adjectives. Treat absence as
        # the unmarked positive convention; NumType and other non-adjectival
        # analyses remain excluded by SAFE_ADJECTIVE_FEATURES.
        and feats.get("Degree") in {None, "Pos"}
        and set(feats).issubset(SAFE_ADJECTIVE_FEATURES)
        and not _has_noisy_features(feats)
    )


def _feature_signature(feats: Mapping[str, str], excluded: set[str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, value) for key, value in feats.items() if key not in excluded))


def build_form_indexes(records: Sequence[Mapping[str, Any]]) -> FormIndexes:
    """Build observed paradigms; no word form is manufactured."""

    verbs: dict[tuple[Any, ...], dict[tuple[str, str], Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    adjective_cases: dict[tuple[Any, ...], dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    adjective_numbers: dict[tuple[Any, ...], dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    for record in records:
        for token in record["tokens"]:
            feats = token["feats"]
            if _safe_verb(token):
                key = (
                    token["lemma"],
                    token["upos"],
                    _feature_signature(feats, {"Person", "Number"}),
                )
                verbs[key][(feats["Person"], feats["Number"])][token["form"]] += 1
            if _safe_adjective(token):
                case_key = (token["lemma"], _feature_signature(feats, {"Case"}))
                number_key = (token["lemma"], _feature_signature(feats, {"Number"}))
                adjective_cases[case_key][feats["Case"]][token["form"]] += 1
                adjective_numbers[number_key][feats["Number"]][token["form"]] += 1
    return FormIndexes(dict(verbs), dict(adjective_cases), dict(adjective_numbers))


def _case_style(form: str) -> str:
    if form.islower():
        return "lower"
    if form[:1].isupper() and form[1:].islower():
        return "title"
    return "other"


def _adapt_sentence_case(evidence_form: str, original_form: str) -> str | None:
    original_style = _case_style(original_form)
    evidence_style = _case_style(evidence_form)
    if original_style == "lower":
        return evidence_form.lower() if evidence_style in {"lower", "title"} else None
    if original_style == "title":
        if evidence_style not in {"lower", "title"}:
            return None
        return evidence_form[:1].upper() + evidence_form[1:].lower()
    return evidence_form if evidence_style == original_style else None


def _best_observation(
    alternatives: Mapping[str | tuple[str, str], Counter[str]],
    *,
    original_value: str | tuple[str, str],
    original_form: str,
    original_feats: Mapping[str, str],
    changed_keys: Sequence[str],
) -> FormObservation | None:
    options: list[tuple[int, str, str | tuple[str, str], str, dict[str, str]]] = []
    for grammatical_value, forms in alternatives.items():
        if grammatical_value == original_value:
            continue
        for evidence_form, count in forms.items():
            replacement = _adapt_sentence_case(evidence_form, original_form)
            if replacement is None or replacement == original_form:
                continue
            replacement_feats = dict(original_feats)
            values = (
                grammatical_value
                if isinstance(grammatical_value, tuple)
                else (grammatical_value,)
            )
            for key, value in zip(changed_keys, values):
                replacement_feats[key] = value
            options.append((-count, replacement.casefold(), grammatical_value, evidence_form, replacement_feats))
    if not options:
        return None
    count_key, _sort_form, grammatical_value, evidence_form, replacement_feats = min(options)
    replacement = _adapt_sentence_case(evidence_form, original_form)
    assert replacement is not None
    return FormObservation(
        grammatical_value=grammatical_value,
        evidence_form=evidence_form,
        evidence_count=-count_key,
        feats=replacement_feats,
    )


def _base_candidate(
    record: Mapping[str, Any],
    token: Mapping[str, Any],
    observation: FormObservation,
    *,
    error_type: str,
    generation_rule: str,
    feature_changes: dict[str, dict[str, str]],
    anchor_token_id: int,
    spans: Mapping[int, tuple[int, int]],
) -> Candidate:
    replacement = _adapt_sentence_case(observation.evidence_form, token["form"])
    if replacement is None:
        raise AssertionError("selected observation cannot preserve casing")
    start, end = spans[token["id"]]
    return Candidate(
        record=record,
        token_id=token["id"],
        lemma=token["lemma"],
        replacement_form=replacement,
        replacement_feats=observation.feats,
        evidence_form=observation.evidence_form,
        evidence_count=observation.evidence_count,
        error_type=error_type,
        generation_rule=generation_rule,
        feature_changes=feature_changes,
        anchor_token_id=anchor_token_id,
        correct_start=start,
        correct_end=end,
    )


def verb_candidates(
    record: Mapping[str, Any],
    indexes: FormIndexes,
    spans: Mapping[int, tuple[int, int]],
) -> list[Candidate]:
    """Return safe overt-subject finite-verb disagreement candidates."""

    candidates: list[Candidate] = []
    for token in record["tokens"]:
        if not _safe_verb(token):
            continue
        feats = token["feats"]
        subjects = [
            subject
            for subject in record["tokens"]
            if subject["head"] == token["id"]
            and subject["deprel"] == "nsubj"
            and subject.get("lemma") in PERSONAL_PRONOUNS
            and subject["feats"].get("Case") == "Nom"
        ]
        if len(subjects) != 1:
            continue
        subject = subjects[0]
        expected = PERSONAL_PRONOUNS[subject["lemma"]]
        original_value = (feats["Person"], feats["Number"])
        if original_value != expected:
            continue
        key = (
            token["lemma"],
            token["upos"],
            _feature_signature(feats, {"Person", "Number"}),
        )
        observation = _best_observation(
            indexes.verbs.get(key, {}),
            original_value=original_value,
            original_form=token["form"],
            original_feats=feats,
            changed_keys=("Person", "Number"),
        )
        if observation is None:
            continue
        new_person, new_number = observation.grammatical_value
        feature_changes = {
            key_name: {"from": feats[key_name], "to": new_value}
            for key_name, new_value in (("Person", new_person), ("Number", new_number))
            if feats[key_name] != new_value
        }
        candidates.append(
            _base_candidate(
                record,
                token,
                observation,
                error_type=VERB_CONJUGATION,
                generation_rule=VERB_RULE,
                feature_changes=feature_changes,
                anchor_token_id=subject["id"],
                spans=spans,
            )
        )
    return candidates


def adjective_candidates(
    record: Mapping[str, Any],
    indexes: FormIndexes,
    spans: Mapping[int, tuple[int, int]],
) -> list[Candidate]:
    """Return narrowly defined adjective case and number disagreement candidates."""

    candidates: list[Candidate] = []
    by_id = {token["id"]: token for token in record["tokens"]}
    for token in record["tokens"]:
        if not _safe_adjective(token):
            continue
        feats = token["feats"]
        head = by_id.get(token["head"])
        if (
            head is None
            or head["upos"] not in {"NOUN", "PROPN"}
            or head["feats"].get("Case") != feats["Case"]
            or head["feats"].get("Number") != feats["Number"]
        ):
            continue

        case_key = (token["lemma"], _feature_signature(feats, {"Case"}))
        case_observation = _best_observation(
            indexes.adjective_cases.get(case_key, {}),
            original_value=feats["Case"],
            original_form=token["form"],
            original_feats=feats,
            changed_keys=("Case",),
        )
        if case_observation is not None:
            candidates.append(
                _base_candidate(
                    record,
                    token,
                    case_observation,
                    error_type=CASE_ERROR,
                    generation_rule=CASE_RULE,
                    feature_changes={
                        "Case": {"from": feats["Case"], "to": str(case_observation.grammatical_value)}
                    },
                    anchor_token_id=head["id"],
                    spans=spans,
                )
            )

        number_key = (token["lemma"], _feature_signature(feats, {"Number"}))
        number_observation = _best_observation(
            indexes.adjective_numbers.get(number_key, {}),
            original_value=feats["Number"],
            original_form=token["form"],
            original_feats=feats,
            changed_keys=("Number",),
        )
        if number_observation is not None:
            candidates.append(
                _base_candidate(
                    record,
                    token,
                    number_observation,
                    error_type=AGREEMENT,
                    generation_rule=AGREEMENT_RULE,
                    feature_changes={
                        "Number": {
                            "from": feats["Number"],
                            "to": str(number_observation.grammatical_value),
                        }
                    },
                    anchor_token_id=head["id"],
                    spans=spans,
                )
            )
    return candidates


def collect_candidates(
    records: Sequence[Mapping[str, Any]],
    indexes: FormIndexes,
    config: GenerationConfig,
) -> tuple[list[Candidate], Counter[str]]:
    """Collect rule-eligible candidates and computed source exclusions."""

    candidates: list[Candidate] = []
    exclusions: Counter[str] = Counter()
    for record in records:
        if record.get("multiword_tokens") or record.get("empty_nodes"):
            exclusions["sentence_has_mwt_or_empty_node"] += 1
            continue
        if not config.minimum_sentence_words <= record["word_count"] <= config.maximum_sentence_words:
            exclusions["sentence_length_outside_limits"] += 1
            continue
        try:
            spans = align_token_spans(record)
        except SpanAlignmentError:
            exclusions["token_alignment_failed"] += 1
            continue
        record_candidates = verb_candidates(record, indexes, spans)
        record_candidates.extend(adjective_candidates(record, indexes, spans))
        if not record_candidates:
            exclusions["no_eligible_rule"] += 1
        candidates.extend(record_candidates)
    return candidates, exclusions


def _candidate_rank(candidate: Candidate, seed: int) -> str:
    return _stable_hash(
        seed,
        candidate.record["leakage_group_id"],
        candidate.error_type,
        candidate.record["source_id"],
        candidate.token_id,
        candidate.replacement_form,
    )


def _candidate_incorrect_sentence(candidate: Candidate) -> str:
    text = candidate.record["original_text"]
    return text[: candidate.correct_start] + candidate.replacement_form + text[candidate.correct_end :]


def _deduplicate_candidates(
    candidates: Sequence[Candidate], seed: int
) -> tuple[list[Candidate], dict[str, int]]:
    exact: dict[tuple[str, str, str], Candidate] = {}
    exact_removed = 0
    for candidate in candidates:
        key = (
            candidate.record["leakage_group_id"],
            candidate.error_type,
            _candidate_incorrect_sentence(candidate),
        )
        incumbent = exact.get(key)
        if incumbent is None or _candidate_rank(candidate, seed) < _candidate_rank(incumbent, seed):
            if incumbent is not None:
                exact_removed += 1
            exact[key] = candidate
        else:
            exact_removed += 1

    by_group_label: dict[tuple[str, str], Candidate] = {}
    group_label_removed = 0
    for candidate in exact.values():
        key = (candidate.record["leakage_group_id"], candidate.error_type)
        incumbent = by_group_label.get(key)
        if incumbent is None or _candidate_rank(candidate, seed) < _candidate_rank(incumbent, seed):
            if incumbent is not None:
                group_label_removed += 1
            by_group_label[key] = candidate
        else:
            group_label_removed += 1
    return list(by_group_label.values()), {
        "exact_duplicate_candidates_removed": exact_removed,
        "extra_candidates_within_group_and_class_removed": group_label_removed,
    }


def select_balanced_candidates(
    candidates: Sequence[Candidate], config: GenerationConfig
) -> tuple[list[Candidate], dict[str, int], dict[str, int]]:
    """Select equal classes with group and lemma caps using stable hash ranks."""

    deduplicated, duplicate_stats = _deduplicate_candidates(candidates, config.random_seed)
    pools = {
        error_type: sorted(
            (candidate for candidate in deduplicated if candidate.error_type == error_type),
            key=lambda candidate: _candidate_rank(candidate, config.random_seed),
        )
        for error_type in ERROR_TYPES
    }
    missing_classes = [error_type for error_type, pool in pools.items() if not pool]
    if missing_classes:
        raise ErrorGenerationError(f"no eligible candidates for classes: {missing_classes}")

    target = min(config.maximum_examples_per_class, *(len(pool) for pool in pools.values()))
    selected_by_class: dict[str, list[Candidate]] = {error_type: [] for error_type in ERROR_TYPES}
    group_counts: Counter[str] = Counter()
    lemma_counts: Counter[tuple[str, str]] = Counter()
    rejection_counts: Counter[str] = Counter()

    # The rare verb class goes first. The common classes still have large pools.
    selection_order = (VERB_CONJUGATION, CASE_ERROR, AGREEMENT)
    for error_type in selection_order:
        for candidate in pools[error_type]:
            if len(selected_by_class[error_type]) >= target:
                rejection_counts["class_cap"] += 1
                continue
            group_id = candidate.record["leakage_group_id"]
            lemma_key = (error_type, candidate.lemma)
            if group_counts[group_id] >= config.maximum_variants_per_leakage_group:
                rejection_counts["leakage_group_cap"] += 1
                continue
            if lemma_counts[lemma_key] >= config.maximum_examples_per_lemma_per_class:
                rejection_counts["lemma_cap"] += 1
                continue
            selected_by_class[error_type].append(candidate)
            group_counts[group_id] += 1
            lemma_counts[lemma_key] += 1

    final_target = min(len(values) for values in selected_by_class.values())
    if final_target < config.minimum_examples_per_class:
        counts = {key: len(value) for key, value in selected_by_class.items()}
        raise ErrorGenerationError(
            f"only {final_target} balanced examples per class survived safety caps; "
            f"minimum is {config.minimum_examples_per_class}. Counts: {counts}"
        )
    for error_type in ERROR_TYPES:
        trimmed = len(selected_by_class[error_type]) - final_target
        if trimmed:
            rejection_counts["class_balance_trim"] += trimmed
            selected_by_class[error_type] = selected_by_class[error_type][:final_target]

    selected = [
        candidate
        for error_type in ERROR_TYPES
        for candidate in selected_by_class[error_type]
    ]
    return selected, duplicate_stats, dict(rejection_counts)


def make_synthetic_id(candidate: Candidate) -> str:
    return "sha256:" + _stable_hash(
        GENERATOR_VERSION,
        candidate.record["source_id"],
        candidate.generation_rule,
        candidate.token_id,
        candidate.replacement_form,
    )


def candidate_to_record(candidate: Candidate) -> dict[str, Any]:
    source = candidate.record
    correct = source["original_text"]
    incorrect = _candidate_incorrect_sentence(candidate)
    incorrect_end = candidate.correct_start + len(candidate.replacement_form)
    source_token = next(token for token in source["tokens"] if token["id"] == candidate.token_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "synthetic_id": make_synthetic_id(candidate),
        "source_id": source["source_id"],
        "leakage_group_id": source["leakage_group_id"],
        "source_dataset": source["source_dataset"],
        "source_commit": source["source_commit"],
        "source_split": source["source_split"],
        "source_file": source["source_file"],
        "source_sentence_id": source["source_sentence_id"],
        "correct_sentence": correct,
        "incorrect_sentence": incorrect,
        "error_type": candidate.error_type,
        "error_span": {
            "start": candidate.correct_start,
            "end": incorrect_end,
            "text": candidate.replacement_form,
        },
        "correction": source_token["form"],
        "generation_rule": candidate.generation_rule,
        "changed_token_id": candidate.token_id,
        "metadata": {
            "correct_span": {
                "start": candidate.correct_start,
                "end": candidate.correct_end,
            },
            "lemma": candidate.lemma,
            "original_form": source_token["form"],
            "replacement_form": candidate.replacement_form,
            "original_feats": source_token["feats"],
            "replacement_feats": candidate.replacement_feats,
            "feature_changes": candidate.feature_changes,
            "anchor_token_id": candidate.anchor_token_id,
            "replacement_evidence_form": candidate.evidence_form,
            "replacement_evidence_count": candidate.evidence_count,
            "generator_version": GENERATOR_VERSION,
        },
    }


def validate_synthetic_record(
    record: Mapping[str, Any], source_by_id: Mapping[str, Mapping[str, Any]]
) -> None:
    """Validate single-error ground truth and exact provenance."""

    missing = SYNTHETIC_REQUIRED_FIELDS - set(record)
    if missing:
        raise ErrorGenerationError(f"synthetic record is missing fields: {sorted(missing)}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ErrorGenerationError("unsupported synthetic schema version")
    source = source_by_id.get(record["source_id"])
    if source is None:
        raise ErrorGenerationError(f"unknown source_id {record['source_id']!r}")
    for field in (
        "leakage_group_id",
        "source_dataset",
        "source_commit",
        "source_split",
        "source_file",
        "source_sentence_id",
    ):
        if record[field] != source[field]:
            raise ErrorGenerationError(f"synthetic {field} does not match its Phase 3 source")
    if record["correct_sentence"] != source["original_text"]:
        raise ErrorGenerationError("correct_sentence does not match Phase 3 original_text")
    if record["correct_sentence"] == record["incorrect_sentence"]:
        raise ErrorGenerationError("synthetic sentence was not changed")
    if RULE_TO_ERROR.get(record["generation_rule"]) != record["error_type"]:
        raise ErrorGenerationError("generation rule and error type do not match")

    error_span = record["error_span"]
    correct_span = record["metadata"].get("correct_span", {})
    try:
        error_start, error_end = int(error_span["start"]), int(error_span["end"])
        correct_start, correct_end = int(correct_span["start"]), int(correct_span["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ErrorGenerationError("invalid error/correct span") from exc
    if error_start != correct_start or min(error_start, error_end, correct_end) < 0:
        raise ErrorGenerationError("error and correction spans must share a valid start")
    incorrect = record["incorrect_sentence"]
    correct = record["correct_sentence"]
    if incorrect[error_start:error_end] != error_span["text"]:
        raise ErrorGenerationError("error_span text does not match incorrect_sentence")
    if correct[correct_start:correct_end] != record["correction"]:
        raise ErrorGenerationError("correction does not match correct_sentence")
    restored = incorrect[:error_start] + record["correction"] + incorrect[error_end:]
    if restored != correct:
        raise ErrorGenerationError("correction does not restore the exact correct sentence")
    if incorrect[:error_start] != correct[:correct_start] or incorrect[error_end:] != correct[correct_end:]:
        raise ErrorGenerationError("unrelated sentence content was changed")

    token = next(
        (token for token in source["tokens"] if token["id"] == record["changed_token_id"]),
        None,
    )
    if token is None or token["form"] != record["correction"]:
        raise ErrorGenerationError("changed_token_id/correction does not identify the source token")
    metadata = record["metadata"]
    if metadata.get("replacement_form") != error_span["text"]:
        raise ErrorGenerationError("replacement metadata does not match the error span")
    if not isinstance(metadata.get("replacement_evidence_count"), int) or metadata[
        "replacement_evidence_count"
    ] < 1:
        raise ErrorGenerationError("replacement has no corpus evidence")
    changes = metadata.get("feature_changes", {})
    expected_change_keys = {
        CASE_RULE: {"Case"},
        AGREEMENT_RULE: {"Number"},
        VERB_RULE: {"Person", "Number"},
    }[record["generation_rule"]]
    if not changes or not set(changes).issubset(expected_change_keys):
        raise ErrorGenerationError("rule changed an unsupported morphological feature")
    if record["generation_rule"] in {CASE_RULE, AGREEMENT_RULE} and set(changes) != expected_change_keys:
        raise ErrorGenerationError("adjective rule did not change exactly its target feature")
    if record["generation_rule"] == VERB_RULE and not set(changes).intersection({"Person", "Number"}):
        raise ErrorGenerationError("verb rule did not change person or number")
    for key, change in changes.items():
        if metadata["original_feats"].get(key) != change.get("from"):
            raise ErrorGenerationError(f"incorrect original feature metadata for {key}")
        if metadata["replacement_feats"].get(key) != change.get("to"):
            raise ErrorGenerationError(f"incorrect replacement feature metadata for {key}")


def _write_jsonl(records: Iterable[Mapping[str, Any]], output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    digest = hashlib.sha256()
    try:
        with temporary.open("wb") as handle:
            for record in records:
                encoded = (
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                ).encode("utf-8")
                handle.write(encoded)
                digest.update(encoded)
        temporary.replace(output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def _manual_review_sample(
    records: Sequence[Mapping[str, Any]], config: GenerationConfig
) -> list[str]:
    selected: list[str] = []
    for error_type in ERROR_TYPES:
        ranked = sorted(
            (record for record in records if record["error_type"] == error_type),
            key=lambda record: _stable_hash(
                config.random_seed, "manual-review", record["synthetic_id"]
            ),
        )
        selected.extend(
            record["synthetic_id"]
            for record in ranked[: config.manual_review_examples_per_class]
        )
    return selected


def build_generation_manifest(
    *,
    config: GenerationConfig,
    processed_path: Path,
    preprocessing_manifest_path: Path,
    phase3_hash: str,
    preprocessing_manifest_hash: str,
    preprocessing_manifest: Mapping[str, Any],
    output_path: Path,
    output_hash: str,
    source_records: Sequence[Mapping[str, Any]],
    raw_candidates: Sequence[Candidate],
    source_exclusions: Mapping[str, int],
    duplicate_stats: Mapping[str, int],
    selection_rejections: Mapping[str, int],
    synthetic_records: Sequence[Mapping[str, Any]],
    validation_failures: Mapping[str, int],
    project_root: Path,
) -> dict[str, Any]:
    def relative(path: Path) -> str:
        try:
            return path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    class_counts = Counter(record["error_type"] for record in synthetic_records)
    candidate_counts = Counter(candidate.error_type for candidate in raw_candidates)
    source_ids = {record["source_id"] for record in source_records}
    leakage_by_source = {
        record["source_id"]: record["leakage_group_id"] for record in source_records
    }
    synthetic_ids = [record["synthetic_id"] for record in synthetic_records]
    duplicate_keys = [
        (record["leakage_group_id"], record["error_type"], record["incorrect_sentence"])
        for record in synthetic_records
    ]
    group_counts = Counter(record["leakage_group_id"] for record in synthetic_records)
    manual_ids = _manual_review_sample(synthetic_records, config)
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "input": {
            "processed_path": relative(processed_path),
            "processed_sha256": phase3_hash,
            "preprocessing_manifest_path": relative(preprocessing_manifest_path),
            "preprocessing_manifest_sha256": preprocessing_manifest_hash,
            "preprocessing_schema_version": preprocessing_manifest["schema_version"],
            "source_sentences": len(source_records),
        },
        "configuration": asdict(config),
        "generation_rules": [
            {
                "generation_rule": rule,
                "error_type": RULE_TO_ERROR[rule],
                "description": RULE_DESCRIPTIONS[rule],
                "replacement_source": "corpus-attested form with matching non-target features",
            }
            for rule in (CASE_RULE, VERB_RULE, AGREEMENT_RULE)
        ],
        "eligible_candidate_counts": dict(sorted(candidate_counts.items())),
        "source_exclusion_counts": dict(sorted(source_exclusions.items())),
        "candidate_rejections": {
            **dict(sorted(duplicate_stats.items())),
            **dict(sorted(selection_rejections.items())),
        },
        "validation_failures": dict(sorted(validation_failures.items())),
        "output": {
            "path": relative(output_path),
            "sha256": output_hash,
            "records": len(synthetic_records),
            "counts_by_class": dict(sorted(class_counts.items())),
            "unique_source_ids": len({record["source_id"] for record in synthetic_records}),
            "unique_leakage_groups": len(group_counts),
            "maximum_variants_in_one_leakage_group": max(group_counts.values(), default=0),
        },
        "duplicate_statistics": {
            "duplicate_synthetic_ids": len(synthetic_ids) - len(set(synthetic_ids)),
            "duplicate_leakage_label_sentence_records": len(duplicate_keys)
            - len(set(duplicate_keys)),
        },
        "manual_review_sample": {
            "selection": "deterministic SHA-256 rank within each class",
            "examples_per_class": config.manual_review_examples_per_class,
            "total_examples": len(manual_ids),
            "synthetic_ids": manual_ids,
            "status": "selected for documented human review; automated checks are not a linguistic guarantee",
        },
        "quality_checks": {
            "phase3_input_hash_verified": phase3_hash
            == preprocessing_manifest["output"]["sha256"],
            "all_source_ids_exist": all(record["source_id"] in source_ids for record in synthetic_records),
            "all_leakage_groups_match_source": all(
                record["leakage_group_id"] == leakage_by_source[record["source_id"]]
                for record in synthetic_records
            ),
            "all_records_validated": not validation_failures,
            "all_synthetic_ids_unique": len(synthetic_ids) == len(set(synthetic_ids)),
            "all_duplicate_keys_unique": len(duplicate_keys) == len(set(duplicate_keys)),
            "classes_balanced": len(set(class_counts.values())) == 1,
            "leakage_group_cap_respected": all(
                count <= config.maximum_variants_per_leakage_group
                for count in group_counts.values()
            ),
            "no_project_split_created": all("split" not in record for record in synthetic_records),
        },
    }


def generate_error_dataset(
    *,
    processed_path: Path,
    preprocessing_manifest_path: Path,
    output_path: Path,
    manifest_path: Path,
    project_root: Path,
    config: GenerationConfig | None = None,
) -> dict[str, Any]:
    """Generate the approved balanced Phase 4 dataset and manifest."""

    config = config or GenerationConfig()
    config.validate()
    source_records, preprocessing_manifest, phase3_hash, manifest_hash = load_phase3_data(
        processed_path, preprocessing_manifest_path
    )
    source_by_id = {record["source_id"]: record for record in source_records}
    indexes = build_form_indexes(source_records)
    raw_candidates, source_exclusions = collect_candidates(source_records, indexes, config)
    selected_candidates, duplicate_stats, selection_rejections = select_balanced_candidates(
        raw_candidates, config
    )

    valid_records: list[dict[str, Any]] = []
    validation_failures: Counter[str] = Counter()
    for candidate in selected_candidates:
        synthetic_record = candidate_to_record(candidate)
        try:
            validate_synthetic_record(synthetic_record, source_by_id)
        except ErrorGenerationError as exc:
            validation_failures[str(exc)] += 1
            continue
        valid_records.append(synthetic_record)
    if validation_failures:
        raise ErrorGenerationError(
            f"selected synthetic candidates failed validation: {dict(validation_failures)}"
        )

    output_hash = _write_jsonl(valid_records, output_path)
    manifest = build_generation_manifest(
        config=config,
        processed_path=processed_path,
        preprocessing_manifest_path=preprocessing_manifest_path,
        phase3_hash=phase3_hash,
        preprocessing_manifest_hash=manifest_hash,
        preprocessing_manifest=preprocessing_manifest,
        output_path=output_path,
        output_hash=output_hash,
        source_records=source_records,
        raw_candidates=raw_candidates,
        source_exclusions=source_exclusions,
        duplicate_stats=duplicate_stats,
        selection_rejections=selection_rejections,
        synthetic_records=valid_records,
        validation_failures=validation_failures,
        project_root=project_root,
    )
    if not all(manifest["quality_checks"].values()):
        raise ErrorGenerationError(
            f"generation quality checks failed: {manifest['quality_checks']}"
        )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(manifest_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return manifest


def run_default_error_generation(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    return generate_error_dataset(
        processed_path=project_root / "data" / "processed" / "finnish_sentences_v1.jsonl",
        preprocessing_manifest_path=project_root
        / "data"
        / "processed"
        / "preprocessing_manifest_v1.json",
        output_path=project_root / "data" / "errors" / "synthetic_errors_v1.jsonl",
        manifest_path=project_root
        / "data"
        / "errors"
        / "error_generation_manifest_v1.json",
        project_root=project_root,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    manifest = run_default_error_generation(args.project_root)
    print(json.dumps(manifest["output"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
