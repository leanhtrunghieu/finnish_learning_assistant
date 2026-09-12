import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

from app.services.error_generation import (
    AGREEMENT,
    CASE_ERROR,
    VERB_CONJUGATION,
    ErrorGenerationError,
    GenerationConfig,
    SpanAlignmentError,
    adjective_candidates,
    align_token_spans,
    build_form_indexes,
    candidate_to_record,
    collect_candidates,
    generate_error_dataset,
    load_phase3_data,
    validate_synthetic_record,
    verb_candidates,
)


COMMIT = "a" * 40


def _leakage(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _token(
    token_id: int,
    form: str,
    lemma: str,
    upos: str,
    feats: dict[str, str],
    head: int,
    deprel: str,
    *,
    misc: dict[str, str] | None = None,
) -> dict:
    return {
        "id": token_id,
        "form": form,
        "lemma": lemma,
        "upos": upos,
        "xpos": upos,
        "feats": feats,
        "head": head,
        "deprel": deprel,
        "misc": misc or {},
    }


def _record(source_sentence_id: str, text: str, tokens: list[dict], **overrides: object) -> dict:
    source_file = "test.conllu"
    dataset = str(overrides.pop("source_dataset", "TEST"))
    record = {
        "schema_version": "1.0",
        "source_dataset": dataset,
        "source_commit": COMMIT,
        "source_split": "train",
        "source_file": source_file,
        "source_sentence_id": source_sentence_id,
        "source_id": f"{dataset}:{source_file}:{source_sentence_id}",
        "leakage_group_id": _leakage(text),
        "original_text": text,
        "word_count": len(tokens),
        "empty_node_count": 0,
        "multiword_tokens": [],
        "empty_nodes": [],
        "tokens": tokens,
    }
    record.update(overrides)
    return record


def _punct(token_id: int, head: int) -> dict:
    return _token(token_id, ".", ".", "PUNCT", {}, head, "punct")


def _verb_pair() -> tuple[dict, dict]:
    source = _record(
        "verb-1",
        "Minä menen kotiin.",
        [
            _token(1, "Minä", "minä", "PRON", {"Case": "Nom", "Number": "Sing", "Person": "1"}, 2, "nsubj"),
            _token(2, "menen", "mennä", "VERB", {"Mood": "Ind", "Number": "Sing", "Person": "1", "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}, 0, "root"),
            _token(3, "kotiin", "koti", "NOUN", {"Case": "Ill", "Number": "Sing"}, 2, "obl", misc={"SpaceAfter": "No"}),
            _punct(4, 2),
        ],
    )
    evidence = _record(
        "verb-2",
        "Sinä menet kotiin.",
        [
            _token(1, "Sinä", "sinä", "PRON", {"Case": "Nom", "Number": "Sing", "Person": "2"}, 2, "nsubj"),
            _token(2, "menet", "mennä", "VERB", {"Mood": "Ind", "Number": "Sing", "Person": "2", "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}, 0, "root"),
            _token(3, "kotiin", "koti", "NOUN", {"Case": "Ill", "Number": "Sing"}, 2, "obl", misc={"SpaceAfter": "No"}),
            _punct(4, 2),
        ],
    )
    return source, evidence


def _case_pair() -> tuple[dict, dict]:
    source = _record(
        "case-1",
        "Suuren talon näen.",
        [
            _token(1, "Suuren", "suuri", "ADJ", {"Case": "Gen", "Degree": "Pos", "Number": "Sing"}, 2, "amod"),
            _token(2, "talon", "talo", "NOUN", {"Case": "Gen", "Number": "Sing"}, 3, "obj"),
            _token(3, "näen", "nähdä", "VERB", {"Mood": "Ind", "Number": "Sing", "Person": "1", "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}, 0, "root", misc={"SpaceAfter": "No"}),
            _punct(4, 3),
        ],
    )
    evidence = _record(
        "case-2",
        "Suurta taloa katson.",
        [
            _token(1, "Suurta", "suuri", "ADJ", {"Case": "Par", "Degree": "Pos", "Number": "Sing"}, 2, "amod"),
            _token(2, "taloa", "talo", "NOUN", {"Case": "Par", "Number": "Sing"}, 3, "obj"),
            _token(3, "katson", "katsoa", "VERB", {"Mood": "Ind", "Number": "Sing", "Person": "1", "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}, 0, "root", misc={"SpaceAfter": "No"}),
            _punct(4, 3),
        ],
    )
    return source, evidence


def _agreement_pair() -> tuple[dict, dict]:
    source = _record(
        "agreement-1",
        "Suuret talot näkyvät.",
        [
            _token(1, "Suuret", "suuri", "ADJ", {"Case": "Nom", "Degree": "Pos", "Number": "Plur"}, 2, "amod"),
            _token(2, "talot", "talo", "NOUN", {"Case": "Nom", "Number": "Plur"}, 3, "nsubj"),
            _token(3, "näkyvät", "näkyä", "VERB", {"Mood": "Ind", "Number": "Plur", "Person": "3", "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}, 0, "root", misc={"SpaceAfter": "No"}),
            _punct(4, 3),
        ],
    )
    evidence = _record(
        "agreement-2",
        "Suuri talo näkyy.",
        [
            _token(1, "Suuri", "suuri", "ADJ", {"Case": "Nom", "Degree": "Pos", "Number": "Sing"}, 2, "amod"),
            _token(2, "talo", "talo", "NOUN", {"Case": "Nom", "Number": "Sing"}, 3, "nsubj"),
            _token(3, "näkyy", "näkyä", "VERB", {"Mood": "Ind", "Number": "Sing", "Person": "3", "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}, 0, "root", misc={"SpaceAfter": "No"}),
            _punct(4, 3),
        ],
    )
    return source, evidence


def _all_records() -> list[dict]:
    records: list[dict] = []
    for pair in (_verb_pair(), _case_pair(), _agreement_pair()):
        records.extend(pair)
    return records


def _write_phase3(tmp_path: Path, records: list[dict]) -> tuple[Path, Path]:
    processed = tmp_path / "phase3.jsonl"
    content = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)
    processed.write_text(content, encoding="utf-8", newline="")
    digest = hashlib.sha256(processed.read_bytes()).hexdigest()
    manifest = tmp_path / "phase3-manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": "1.0", "output": {"sha256": digest, "sentences": len(records)}}),
        encoding="utf-8",
    )
    return processed, manifest


def _small_config(seed: int = 42) -> GenerationConfig:
    return GenerationConfig(
        random_seed=seed,
        maximum_examples_per_class=1,
        minimum_examples_per_class=1,
        maximum_variants_per_leakage_group=2,
        maximum_examples_per_lemma_per_class=10,
        minimum_sentence_words=3,
        maximum_sentence_words=30,
        manual_review_examples_per_class=1,
    )


def test_token_alignment_preserves_multiple_spaces_and_punctuation() -> None:
    record = _record(
        "spaces",
        "Äiti  näkee talon.",
        [
            _token(1, "Äiti", "äiti", "NOUN", {"Case": "Nom", "Number": "Sing"}, 2, "nsubj"),
            _token(2, "näkee", "nähdä", "VERB", {"Mood": "Ind", "Number": "Sing", "Person": "3", "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}, 0, "root"),
            _token(3, "talon", "talo", "NOUN", {"Case": "Gen", "Number": "Sing"}, 2, "obj", misc={"SpaceAfter": "No"}),
            _punct(4, 2),
        ],
    )

    spans = align_token_spans(record)

    assert record["original_text"][slice(*spans[1])] == "Äiti"
    assert record["original_text"][slice(*spans[3])] == "talon"
    assert record["original_text"][slice(*spans[4])] == "."


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("multiword_tokens", [{"id": "1-2", "form": "Minämenen"}]),
        ("empty_nodes", [{"id": "2.1", "form": "mennä"}]),
    ],
)
def test_mwt_and_empty_nodes_are_rejected_for_alignment(field: str, value: list[dict]) -> None:
    record, _ = _verb_pair()
    record[field] = value

    with pytest.raises(SpanAlignmentError, match="MWTs or empty nodes"):
        align_token_spans(record)


def test_approved_rules_are_eligible_and_have_known_corrections() -> None:
    records = _all_records()
    indexes = build_form_indexes(records)
    verb_source, _ = _verb_pair()
    case_source, _ = _case_pair()
    agreement_source, _ = _agreement_pair()

    verb = verb_candidates(verb_source, indexes, align_token_spans(verb_source))[0]
    case = [candidate for candidate in adjective_candidates(case_source, indexes, align_token_spans(case_source)) if candidate.error_type == CASE_ERROR][0]
    agreement = [candidate for candidate in adjective_candidates(agreement_source, indexes, align_token_spans(agreement_source)) if candidate.error_type == AGREEMENT][0]

    assert (verb.error_type, candidate_to_record(verb)["correction"]) == (VERB_CONJUGATION, "menen")
    assert (case.error_type, candidate_to_record(case)["correction"]) == (CASE_ERROR, "Suuren")
    assert (agreement.error_type, candidate_to_record(agreement)["correction"]) == (AGREEMENT, "Suuret")


def test_unmarked_positive_ftb_adjectives_are_eligible() -> None:
    source, evidence = _case_pair()
    source["source_dataset"] = "UD_Finnish-FTB"
    evidence["source_dataset"] = "UD_Finnish-FTB"
    for record in (source, evidence):
        record["tokens"][0]["feats"].pop("Degree")
    indexes = build_form_indexes([source, evidence])

    candidates = adjective_candidates(source, indexes, align_token_spans(source))

    assert any(candidate.error_type == CASE_ERROR for candidate in candidates)


def test_comparative_adjectives_remain_ineligible() -> None:
    source, evidence = _case_pair()
    for record in (source, evidence):
        record["tokens"][0]["feats"]["Degree"] = "Cmp"

    indexes = build_form_indexes([source, evidence])

    assert adjective_candidates(source, indexes, align_token_spans(source)) == []


def test_rule_rejection_for_missing_subject_and_mismatched_modifier() -> None:
    records = _all_records()
    indexes = build_form_indexes(records)
    verb_source, _ = _verb_pair()
    verb_source["tokens"][0]["deprel"] = "obl"
    case_source, _ = _case_pair()
    case_source["tokens"][1]["feats"]["Case"] = "Nom"

    assert verb_candidates(verb_source, indexes, align_token_spans(verb_source)) == []
    assert adjective_candidates(case_source, indexes, align_token_spans(case_source)) == []


def test_person_zero_verb_form_is_not_used_as_a_replacement() -> None:
    source, evidence = _verb_pair()
    evidence["tokens"][1]["feats"]["Person"] = "0"
    indexes = build_form_indexes([source, evidence])

    assert verb_candidates(source, indexes, align_token_spans(source)) == []


def test_synthetic_record_propagates_provenance_leakage_and_changes_one_span() -> None:
    records = _all_records()
    source, _ = _case_pair()
    candidate = next(
        candidate
        for candidate in adjective_candidates(source, build_form_indexes(records), align_token_spans(source))
        if candidate.error_type == CASE_ERROR
    )
    synthetic = candidate_to_record(candidate)

    validate_synthetic_record(synthetic, {source["source_id"]: source})
    assert synthetic["source_id"] == source["source_id"]
    assert synthetic["leakage_group_id"] == source["leakage_group_id"]
    assert synthetic["incorrect_sentence"] == f"{candidate.replacement_form} talon näen."
    assert synthetic["correction"] == "Suuren"
    assert synthetic["incorrect_sentence"].endswith(".")
    span = synthetic["error_span"]
    restored = synthetic["incorrect_sentence"][: span["start"]] + synthetic["correction"] + synthetic["incorrect_sentence"][span["end"] :]
    assert restored == synthetic["correct_sentence"]


def test_generation_preserves_unicode_casing_and_unrelated_text() -> None:
    source, evidence = _case_pair()
    source["original_text"] = "Äärettömän  talon näen!"
    source["tokens"][0].update(form="Äärettömän", lemma="ääretön")
    source["tokens"][-1].update(form="!", lemma="!")
    source["leakage_group_id"] = _leakage(source["original_text"])
    evidence["tokens"][0].update(form="ääretöntä", lemma="ääretön")
    indexes = build_form_indexes([source, evidence])
    candidate = adjective_candidates(source, indexes, align_token_spans(source))[0]
    synthetic = candidate_to_record(candidate)

    assert synthetic["incorrect_sentence"] == "Ääretöntä  talon näen!"
    assert "ää" in synthetic["incorrect_sentence"].lower()
    assert synthetic["incorrect_sentence"].endswith("!")
    assert "  " in synthetic["incorrect_sentence"]


def test_full_generation_is_reproducible_with_fixed_seed(tmp_path: Path) -> None:
    processed, phase3_manifest = _write_phase3(tmp_path, _all_records())
    first_output, first_manifest = tmp_path / "first.jsonl", tmp_path / "first-manifest.json"
    second_output, second_manifest = tmp_path / "second.jsonl", tmp_path / "second-manifest.json"

    first = generate_error_dataset(
        processed_path=processed,
        preprocessing_manifest_path=phase3_manifest,
        output_path=first_output,
        manifest_path=first_manifest,
        project_root=tmp_path,
        config=_small_config(),
    )
    second = generate_error_dataset(
        processed_path=processed,
        preprocessing_manifest_path=phase3_manifest,
        output_path=second_output,
        manifest_path=second_manifest,
        project_root=tmp_path,
        config=_small_config(),
    )

    assert first_output.read_bytes() == second_output.read_bytes()
    assert first["output"]["sha256"] == second["output"]["sha256"]
    assert first["output"]["counts_by_class"] == {AGREEMENT: 1, CASE_ERROR: 1, VERB_CONJUGATION: 1}


def test_duplicate_source_text_does_not_create_duplicate_synthetic_examples(tmp_path: Path) -> None:
    records = _all_records()
    duplicate = json.loads(json.dumps(_case_pair()[0]))
    duplicate["source_sentence_id"] = "case-duplicate"
    duplicate["source_id"] = "TEST:test.conllu:case-duplicate"
    records.append(duplicate)
    processed, phase3_manifest = _write_phase3(tmp_path, records)

    manifest = generate_error_dataset(
        processed_path=processed,
        preprocessing_manifest_path=phase3_manifest,
        output_path=tmp_path / "out.jsonl",
        manifest_path=tmp_path / "out-manifest.json",
        project_root=tmp_path,
        config=_small_config(),
    )

    assert manifest["duplicate_statistics"]["duplicate_synthetic_ids"] == 0
    assert manifest["duplicate_statistics"]["duplicate_leakage_label_sentence_records"] == 0
    assert sum(manifest["candidate_rejections"].values()) > 0


def test_invalid_phase3_hash_is_rejected(tmp_path: Path) -> None:
    processed, manifest = _write_phase3(tmp_path, _all_records())
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["output"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ErrorGenerationError, match="hash mismatch"):
        load_phase3_data(processed, manifest)


def test_invalid_synthetic_source_id_is_rejected() -> None:
    records = _all_records()
    source, _ = _verb_pair()
    candidate = verb_candidates(source, build_form_indexes(records), align_token_spans(source))[0]
    synthetic = candidate_to_record(candidate)
    synthetic["source_id"] = "missing"

    with pytest.raises(ErrorGenerationError, match="unknown source_id"):
        validate_synthetic_record(synthetic, {source["source_id"]: source})


def test_unrelated_text_modification_is_rejected() -> None:
    records = _all_records()
    source, _ = _verb_pair()
    candidate = verb_candidates(source, build_form_indexes(records), align_token_spans(source))[0]
    synthetic = candidate_to_record(candidate)
    synthetic["incorrect_sentence"] = synthetic["incorrect_sentence"].replace("kotiin", "kotiin!")

    with pytest.raises(ErrorGenerationError, match="restore the exact correct sentence"):
        validate_synthetic_record(synthetic, {source["source_id"]: source})


def test_collection_reports_special_row_and_length_rejections() -> None:
    source, evidence = _verb_pair()
    special = json.loads(json.dumps(source))
    special["source_id"] = "TEST:test.conllu:special"
    special["source_sentence_id"] = "special"
    special["multiword_tokens"] = [{"id": "1-2", "form": "Minämenen"}]
    too_short = _record("short", "Hei!", [_token(1, "Hei", "hei", "INTJ", {}, 0, "root", misc={"SpaceAfter": "No"}), _punct(2, 1)])

    _, exclusions = collect_candidates([special, too_short], build_form_indexes([source, evidence]), GenerationConfig())

    assert exclusions["sentence_has_mwt_or_empty_node"] == 1
    assert exclusions["sentence_length_outside_limits"] == 1


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ErrorGenerationError, match="minimum_examples_per_class"):
        GenerationConfig(maximum_examples_per_class=1, minimum_examples_per_class=2).validate()
