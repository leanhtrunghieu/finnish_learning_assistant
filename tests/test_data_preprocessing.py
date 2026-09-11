import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

from app.services.data_preprocessing import (
    ConlluValidationError,
    SourceSpec,
    build_manifest,
    iter_conllu_sentences,
    make_leakage_group_id,
    make_source_id,
    parse_feats,
    parse_source,
    preprocess_sources,
    write_jsonl,
)


COMMIT = "a" * 40


def _word(
    token_id: int,
    form: str,
    *,
    lemma: str = "sana",
    upos: str = "NOUN",
    xpos: str = "N",
    feats: str = "Case=Nom|Number=Sing",
    head: int = 0,
    deprel: str = "root",
    misc: str = "_",
) -> str:
    return "\t".join(
        [str(token_id), form, lemma, upos, xpos, feats, str(head), deprel, "_", misc]
    )


def _sentence(sent_id: str, text: str, rows: list[str]) -> str:
    return f"# sent_id = {sent_id}\n# text = {text}\n" + "\n".join(rows) + "\n"


def _spec(path: Path, dataset: str = "TEST", split: str = "train") -> SourceSpec:
    return SourceSpec(dataset=dataset, commit=COMMIT, split=split, path=path)


def _write_source(tmp_path: Path, content: str, name: str = "sample.conllu") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8", newline="")
    return path


def test_sentence_boundaries_are_preserved(tmp_path: Path) -> None:
    content = (
        _sentence("s1", "Ensimmäinen.", [_word(1, "Ensimmäinen.")])
        + "\n"
        + _sentence("s2", "Toinen!", [_word(1, "Toinen!")])
    )
    records = list(iter_conllu_sentences(_spec(_write_source(tmp_path, content))))

    assert [record["source_sentence_id"] for record in records] == ["s1", "s2"]
    assert [record["original_text"] for record in records] == ["Ensimmäinen.", "Toinen!"]


def test_eof_finishes_sentence_without_trailing_blank_line(tmp_path: Path) -> None:
    content = _sentence("s1", "Loppu", [_word(1, "Loppu")]).rstrip("\n")

    records = list(iter_conllu_sentences(_spec(_write_source(tmp_path, content))))

    assert len(records) == 1
    assert records[0]["word_count"] == 1


def test_normal_integer_ids_are_typed_and_ordered(tmp_path: Path) -> None:
    rows = [
        _word(1, "Minä", lemma="minä", upos="PRON", xpos="Pron", feats="Case=Nom|Number=Sing|Person=1", head=2, deprel="nsubj"),
        _word(2, "menen", lemma="mennä", upos="VERB", xpos="V", feats="Mood=Ind|Number=Sing|Person=1|Tense=Pres|VerbForm=Fin|Voice=Act"),
    ]
    record = next(iter_conllu_sentences(_spec(_write_source(tmp_path, _sentence("s1", "Minä menen", rows)))))

    assert [token["id"] for token in record["tokens"]] == [1, 2]
    assert all(isinstance(token["id"], int) for token in record["tokens"])


def test_multiword_token_range_is_separate_from_words(tmp_path: Path) -> None:
    rows = [
        "1-2\tenkö\t_\t_\t_\t_\t_\t_\t_\tSpaceAfter=No",
        _word(1, "en", lemma="ei", upos="AUX", xpos="V", feats="Number=Sing|Person=1|Polarity=Neg", head=2, deprel="aux"),
        _word(2, "kö", lemma="kö", upos="PART", xpos="Pcle", feats="_"),
    ]
    record = next(iter_conllu_sentences(_spec(_write_source(tmp_path, _sentence("s1", "enkö", rows)))))

    assert record["word_count"] == 2
    assert record["multiword_tokens"] == [
        {"id": "1-2", "start": 1, "end": 2, "form": "enkö", "misc": {"SpaceAfter": "No"}}
    ]


def test_empty_node_is_preserved_separately(tmp_path: Path) -> None:
    rows = [
        _word(1, "Hän", lemma="hän", upos="PRON", xpos="Pron", feats="Case=Nom|Number=Sing|Person=3"),
        "1.1\tolisi\tolla\tAUX\tV\tMood=Cnd|VerbForm=Fin\t_\t_\t1:cop\t_",
    ]
    record = next(iter_conllu_sentences(_spec(_write_source(tmp_path, _sentence("s1", "Hän", rows)))))

    assert record["empty_node_count"] == 1
    assert record["empty_nodes"][0]["id"] == "1.1"
    assert record["empty_nodes"][0]["head"] is None
    assert len(record["tokens"]) == 1


def test_malformed_column_count_fails_with_context(tmp_path: Path) -> None:
    path = _write_source(tmp_path, "# sent_id = bad\n1\ttoo\tfew\n")

    with pytest.raises(ConlluValidationError, match=r"line 2, sentence 1.*expected 10"):
        list(iter_conllu_sentences(_spec(path)))


def test_missing_optional_annotations_are_retained(tmp_path: Path) -> None:
    row = _word(1, "Sana", lemma="_", xpos="_", feats="_", misc="_")
    record = next(iter_conllu_sentences(_spec(_write_source(tmp_path, _sentence("s1", "Sana", [row])))))
    token = record["tokens"][0]

    assert token["lemma"] is None
    assert token["xpos"] is None
    assert token["feats"] == {}
    assert token["misc"] == {}


def test_feats_are_parsed_without_losing_finnish_morphology() -> None:
    assert parse_feats("Case=Ill|Number=Plur|Person[psor]=1") == {
        "Case": "Ill",
        "Number": "Plur",
        "Person[psor]": "1",
    }


@pytest.mark.parametrize("value", ["Case", "=Nom", "Case=", "Case=Nom|Case=Gen", "Number=Sing|Case=Nom"])
def test_malformed_feats_fail(value: str) -> None:
    with pytest.raises(ConlluValidationError):
        parse_feats(value)


def test_finnish_unicode_capitalization_and_punctuation_are_preserved(tmp_path: Path) -> None:
    text = "Äiti kysyi: “Syötkö jäätelöä?”"
    row = _word(1, "Äiti", lemma="äiti")
    record = next(iter_conllu_sentences(_spec(_write_source(tmp_path, _sentence("s1", text, [row])))))

    assert record["original_text"] == text
    assert record["original_text"].startswith("Ä")
    assert "ä" in record["original_text"]
    assert ": “" in record["original_text"] and record["original_text"].endswith("?”")
    assert record["original_text"] != record["original_text"].lower()


def test_dependency_reference_must_exist(tmp_path: Path) -> None:
    row = _word(1, "Virhe", head=2, deprel="nsubj")
    path = _write_source(tmp_path, _sentence("bad-head", "Virhe", [row]))

    with pytest.raises(ConlluValidationError, match="does not reference"):
        list(iter_conllu_sentences(_spec(path)))


def test_dependency_cycles_are_rejected(tmp_path: Path) -> None:
    rows = [
        _word(1, "Juuri", upos="ADV", xpos="Adv"),
        _word(2, "Kaksi", head=3, deprel="nmod"),
        _word(3, "Kolme", head=2, deprel="nmod"),
    ]
    path = _write_source(tmp_path, _sentence("cycle", "Juuri kaksi kolme", rows))

    with pytest.raises(ConlluValidationError, match="dependency cycle"):
        list(iter_conllu_sentences(_spec(path)))


def test_source_ids_are_deterministic() -> None:
    expected = "UD_Finnish-TDT:fi_tdt-ud-train.conllu:b101.1"
    assert make_source_id("UD_Finnish-TDT", "fi_tdt-ud-train.conllu", "b101.1") == expected
    assert make_source_id("UD_Finnish-TDT", "fi_tdt-ud-train.conllu", "b101.1") == expected


def test_missing_sentence_id_gets_deterministic_line_fallback(tmp_path: Path) -> None:
    path = _write_source(tmp_path, "# text = Sana\n" + _word(1, "Sana") + "\n")
    first = list(iter_conllu_sentences(_spec(path)))[0]
    second = list(iter_conllu_sentences(_spec(path)))[0]

    assert first["source_sentence_id"] == "line-1"
    assert first["source_id"] == second["source_id"]


def test_leakage_group_ids_are_deterministic_and_nfc_normalized() -> None:
    composed = "Hyvää päivää!"
    decomposed = unicodedata.normalize("NFD", composed)

    assert composed != decomposed
    assert make_leakage_group_id(composed) == make_leakage_group_id(decomposed)
    expected_hash = hashlib.sha256(composed.encode("utf-8")).hexdigest()
    assert make_leakage_group_id(composed) == f"sha256:{expected_hash}"


def test_duplicate_texts_are_retained_and_grouped(tmp_path: Path) -> None:
    first_path = _write_source(tmp_path, _sentence("a", "Sama teksti.", [_word(1, "Sama")]), "a.conllu")
    second_path = _write_source(tmp_path, _sentence("b", "Sama teksti.", [_word(1, "Sama")]), "b.conllu")
    output = tmp_path / "out.jsonl"
    manifest_path = tmp_path / "manifest.json"

    manifest = preprocess_sources(
        [_spec(first_path, "A"), _spec(second_path, "B")],
        output_path=output,
        manifest_path=manifest_path,
        project_root=tmp_path,
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 2
    assert records[0]["leakage_group_id"] == records[1]["leakage_group_id"]
    assert manifest["duplicate_statistics"]["duplicate_text_groups"] == 1
    assert manifest["duplicate_statistics"]["cross_dataset_duplicate_text_groups"] == 1


def test_duplicate_sentence_ids_in_one_file_are_rejected(tmp_path: Path) -> None:
    content = _sentence("same", "Yksi", [_word(1, "Yksi")]) + "\n" + _sentence("same", "Kaksi", [_word(1, "Kaksi")])
    path = _write_source(tmp_path, content)

    with pytest.raises(ConlluValidationError, match="duplicate source IDs"):
        parse_source(_spec(path))


def test_jsonl_round_trip_preserves_unicode_and_types(tmp_path: Path) -> None:
    path = _write_source(tmp_path, _sentence("s1", "Ääkköset!", [_word(1, "Ääkköset!")]))
    record = list(iter_conllu_sentences(_spec(path)))[0]
    output = tmp_path / "round-trip.jsonl"

    digest = write_jsonl([record], output)
    loaded = json.loads(output.read_text(encoding="utf-8"))

    assert loaded == record
    assert "Ääkköset!" in output.read_text(encoding="utf-8")
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()


def test_manifest_counts_are_calculated_from_records(tmp_path: Path) -> None:
    path = _write_source(tmp_path, _sentence("s1", "Sana", [_word(1, "Sana", lemma="_")]))
    parsed = parse_source(_spec(path))
    output = tmp_path / "out.jsonl"
    output_hash = write_jsonl(parsed.records, output)

    manifest = build_manifest([parsed], parsed.records, project_root=tmp_path, output_path=output, output_sha256=output_hash)

    assert manifest["input_counts"]["total"]["sentences"] == len(parsed.records)
    assert manifest["output"]["word_tokens"] == sum(record["word_count"] for record in parsed.records)
    assert manifest["missing_value_statistics"]["lemma"]["missing_count"] == 1
