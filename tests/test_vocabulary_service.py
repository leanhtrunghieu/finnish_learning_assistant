import json
from pathlib import Path

import pytest

from app.models.vocabulary import VocabularyStatus
from app.services.vocabulary_service import (
    VocabularyInputError,
    VocabularyService,
    build_vocabulary_index,
    normalize_lookup_key,
)


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    processed = tmp_path / "sentences.jsonl"
    rows = [
        {
            "original_text": "Minä olen koulussa.",
            "source_id": "TDT:one",
            "source_dataset": "UD_Finnish-TDT",
            "word_count": 4,
            "tokens": [
                {"form": "Minä", "lemma": "minä", "upos": "PRON", "feats": {"Case": "Nom"}, "misc": {}},
                {"form": "olen", "lemma": "olla", "upos": "AUX", "feats": {}, "misc": {}},
                {"form": "koulussa", "lemma": "koulu", "upos": "NOUN", "feats": {"Case": "Ine", "Number": "Sing"}, "misc": {}},
                {"form": ".", "lemma": ".", "upos": "PUNCT", "feats": {}, "misc": {}},
            ],
        },
        {
            "original_text": "Menen kouluun.",
            "source_id": "TDT:two",
            "source_dataset": "UD_Finnish-TDT",
            "word_count": 3,
            "tokens": [
                {"form": "Menen", "lemma": "mennä", "upos": "VERB", "feats": {"VerbForm": "Fin"}, "misc": {}},
                {"form": "kouluun", "lemma": "koulu", "upos": "NOUN", "feats": {"Case": "Ill", "Number": "Sing"}, "misc": {}},
                {"form": ".", "lemma": ".", "upos": "PUNCT", "feats": {}, "misc": {}},
            ],
        },
        {
            "original_text": "Kuusi kasvaa.",
            "source_id": "FTB:one",
            "source_dataset": "UD_Finnish-FTB",
            "word_count": 3,
            "tokens": [
                {"form": "Kuusi", "lemma": "kuusi", "upos": "NOUN", "feats": {"Case": "Nom"}, "misc": {}},
                {"form": "kasvaa", "lemma": "kasvaa", "upos": "VERB", "feats": {}, "misc": {}},
                {"form": ".", "lemma": ".", "upos": "PUNCT", "feats": {}, "misc": {}},
            ],
        },
        {
            "original_text": "Kuusi on numero.",
            "source_id": "FTB:two",
            "source_dataset": "UD_Finnish-FTB",
            "word_count": 4,
            "tokens": [
                {"form": "Kuusi", "lemma": "kuusi", "upos": "NUM", "feats": {"NumType": "Card"}, "misc": {}},
                {"form": "on", "lemma": "olla", "upos": "AUX", "feats": {"Mood": "Ind", "Number": "Sing", "Person": "3"}, "misc": {}},
                {"form": "numero", "lemma": "numero", "upos": "NOUN", "feats": {"Case": "Nom"}, "misc": {}},
                {"form": ".", "lemma": ".", "upos": "PUNCT", "feats": {}, "misc": {}},
            ],
        },
        {
            "original_text": "Ne on täällä.",
            "source_id": "FTB:three",
            "source_dataset": "UD_Finnish-FTB",
            "word_count": 4,
            "tokens": [
                {"form": "Ne", "lemma": "se", "upos": "PRON", "feats": {"Number": "Plur"}, "misc": {}},
                {"form": "on", "lemma": "olla", "upos": "AUX", "feats": {"Mood": "Ind", "Number": "Plur", "Person": "3", "Style": "Coll"}, "misc": {}},
                {"form": "täällä", "lemma": "täällä", "upos": "ADV", "feats": {}, "misc": {}},
                {"form": ".", "lemma": ".", "upos": "PUNCT", "feats": {}, "misc": {}},
            ],
        },
    ]
    processed.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    fwn_root = tmp_path / "FinnWordNet-2.0"
    lists = fwn_root / "lists"
    lists.mkdir(parents=True)
    (lists / "fiwn-synsets-extra.tsv").write_text(
        "\n".join(
            [
                "fi:n00000001\tN\tkoulu\ta building for education\tschool\t\tartifact",
                "fi:v00000002\tV\tmennä\tto move\tgo\t\tmotion",
                "fi:n00000003\tN\tkuusi<unconfirmed/>\tthe number six\tsix\t\tquantity",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return processed, fwn_root


def test_normalization_preserves_finnish_unicode():
    assert normalize_lookup_key(" ÄÖ ") == "äö"


def test_index_build_and_inflected_lookup(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    manifest = tmp_path / "manifest.json"
    build_vocabulary_index(processed, fwn_root, output, manifest)
    service = VocabularyService(output)

    result = service.lookup(" Koulussa ")
    assert result.status is VocabularyStatus.FOUND
    assert result.query == "Koulussa"
    assert result.analyses[0].lemma == "koulu"
    assert result.analyses[0].meanings == ["school"]
    assert any(form.form == "koulussa" and form.features["Case"] == "Ine" for form in result.analyses[0].observed_forms)
    assert result.analyses[0].example is not None
    assert result.analyses[0].example.source_id == "TDT:one"
    assert any(source.source_id == "finnwordnet-2.0" for source in result.analyses[0].sources)


def test_ambiguity_is_exposed(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    build_vocabulary_index(processed, fwn_root, output, tmp_path / "manifest.json")
    result = VocabularyService(output).lookup("kuusi")
    assert result.status is VocabularyStatus.AMBIGUOUS
    assert {analysis.part_of_speech for analysis in result.analyses} == {"NOUN", "NUM"}
    assert result.warnings


def test_morphological_ambiguity_is_preserved(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    build_vocabulary_index(processed, fwn_root, output, tmp_path / "manifest.json")
    result = VocabularyService(output).lookup("on")
    observed = next(form for form in result.analyses[0].observed_forms if form.matches_query)
    assert len(observed.feature_analyses) == 2
    assert {analysis.features["Number"] for analysis in observed.feature_analyses} == {"Sing", "Plur"}
    assert "multiple observed morphological analyses" in " ".join(result.warnings)


def test_qualified_finnwordnet_translation_is_not_overstated(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    manifest_path = tmp_path / "manifest.json"
    build_vocabulary_index(processed, fwn_root, output, manifest_path)
    result = VocabularyService(output).lookup("kuusi")
    noun = next(analysis for analysis in result.analyses if analysis.part_of_speech == "NOUN")
    assert "six" not in noun.meanings
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["finnwordnet_parsing"]["qualified_finnish_terms_excluded"] == 1


def test_unknown_word_is_structured_not_found(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    build_vocabulary_index(processed, fwn_root, output, tmp_path / "manifest.json")
    result = VocabularyService(output).lookup("qwertyö")
    assert result.status is VocabularyStatus.NOT_FOUND
    assert result.analyses == []


def test_known_word_without_english_meaning_stays_empty(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    build_vocabulary_index(processed, fwn_root, output, tmp_path / "manifest.json")
    result = VocabularyService(output).lookup("minä")
    assert result.status is VocabularyStatus.FOUND
    assert result.analyses[0].meanings == []
    assert [source.source_id for source in result.analyses[0].sources] == [
        "phase3-finnish-corpus-v1"
    ]


def test_lookup_preserves_query_capitalization(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    build_vocabulary_index(processed, fwn_root, output, tmp_path / "manifest.json")
    result = VocabularyService(output).lookup("KOULUSSA")
    assert result.query == "KOULUSSA"
    assert result.status is VocabularyStatus.FOUND


@pytest.mark.parametrize("query", ["", "   ", "koulussa täällä"])
def test_invalid_queries_fail_cleanly(tmp_path: Path, query: str):
    processed, fwn_root = _write_fixture(tmp_path)
    output = tmp_path / "index.jsonl"
    build_vocabulary_index(processed, fwn_root, output, tmp_path / "manifest.json")
    with pytest.raises(VocabularyInputError):
        VocabularyService(output).lookup(query)


def test_index_build_is_deterministic_and_manifest_is_computed(tmp_path: Path):
    processed, fwn_root = _write_fixture(tmp_path)
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    build_vocabulary_index(processed, fwn_root, first, tmp_path / "first.json")
    build_vocabulary_index(processed, fwn_root, second, tmp_path / "second.json")
    assert first.read_bytes() == second.read_bytes()
    manifest = json.loads((tmp_path / "first.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["analysis_records"] > 0
    assert manifest["quality_checks"]["generated_forms"] is False
    assert manifest["output_sha256"]


def test_malformed_index_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"schema_version":"wrong"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported vocabulary index schema"):
        VocabularyService(path)


def test_malformed_nested_index_fields_are_rejected(tmp_path: Path):
    path = tmp_path / "bad-fields.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "lemma": "koulu",
                "part_of_speech": "NOUN",
                "lookup_keys": ["koulu"],
                "meanings": "school",
                "observed_forms": [],
                "source_ids": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid meanings"):
        VocabularyService(path)
