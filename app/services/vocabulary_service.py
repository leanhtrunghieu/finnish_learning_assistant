"""Deterministic Finnish vocabulary index construction and lookup.

The service deliberately separates factual sources: FinnWordNet supplies
Finnish lexical meanings/POS, while the Phase 3 UD corpus supplies observed
forms, annotations, frequencies, and short examples.  It does not generate
unobserved Finnish morphology and does not call an LLM.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterable

from app.models.vocabulary import (
    ObservedFeatureAnalysis,
    ObservedForm,
    VocabularyAnalysis,
    VocabularyExample,
    VocabularyResult,
    VocabularySource,
    VocabularyStatus,
)

SCHEMA_VERSION = "1.0"
FINNWORDNET_SOURCE = VocabularySource(
    source_id="finnwordnet-2.0",
    name="FinnWordNet",
    version="2.0",
    url="https://www.kielipankki.fi/download/FinnWordNet/v2.0/FinnWordNet-2.0.zip",
    license="Princeton WordNet license + CC BY 3.0",
    fields=["lemma", "part_of_speech", "meanings"],
)
CORPUS_SOURCE = VocabularySource(
    source_id="phase3-finnish-corpus-v1",
    name="UD Finnish-TDT + UD Finnish-FTB (Phase 3 processed corpus)",
    version="Phase 3 v1",
    url="https://universaldependencies.org/treebanks/fi_tdt/index.html",
    license="TDT CC BY-SA 4.0; FTB CC BY 4.0",
    fields=["observed_forms", "morphology", "frequency", "example"],
)
_SOURCES_BY_ID = {
    FINNWORDNET_SOURCE.source_id: FINNWORDNET_SOURCE,
    CORPUS_SOURCE.source_id: CORPUS_SOURCE,
}

_TAG_RE = re.compile(r"<[^>]+>")
_FWN_TO_UPOS = {"N": "NOUN", "V": "VERB", "A": "ADJ", "S": "ADJ", "R": "ADV"}


class VocabularyInputError(ValueError):
    """Raised when a lookup query is empty or outside the MVP token scope."""


def normalize_lookup_key(value: str) -> str:
    """Normalize only the lookup key; never rewrite the returned query/forms."""

    return unicodedata.normalize("NFC", value.strip()).casefold()


def validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise VocabularyInputError("Vocabulary query must be a string")
    normalized = unicodedata.normalize("NFC", query.strip())
    if not normalized:
        raise VocabularyInputError("Vocabulary query must not be empty")
    if any(char.isspace() for char in normalized):
        raise VocabularyInputError("Phase 8 lookup accepts one Finnish word or token")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_text(value: str) -> str:
    return _TAG_RE.sub("", value).strip()


def _meaning_terms(value: str) -> list[str]:
    terms: list[str] = []
    for term in value.split(" | "):
        clean = _clean_text(term)
        if clean and clean not in terms:
            terms.append(clean)
    return terms


def _resolve_finnwordnet_root(root: Path) -> Path:
    candidates = [root, root / "FinnWordNet-2.0"]
    candidates.extend(sorted(root.glob("*/")))
    for candidate in candidates:
        if (candidate / "lists" / "fiwn-synsets-extra.tsv").is_file():
            return candidate
    raise FileNotFoundError(
        f"FinnWordNet root must contain lists/fiwn-synsets-extra.tsv: {root}"
    )


def _load_finnwordnet(
    root: Path,
) -> tuple[dict[tuple[str, str], set[str]], dict[str, int]]:
    """Load concise English meanings keyed by Finnish lemma and UPOS."""

    root = _resolve_finnwordnet_root(root)
    meanings: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    stats = {
        "rows_read": 0,
        "qualified_finnish_terms_excluded": 0,
        "multiword_finnish_terms_excluded": 0,
        "accepted_finnish_terms": 0,
    }
    path = root / "lists" / "fiwn-synsets-extra.tsv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            stats["rows_read"] += 1
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 7:
                raise ValueError(f"Malformed FinnWordNet row at {path}:{line_number}")
            _synset, fwn_pos, finnish_synonyms, gloss, english_synonyms, _hypernyms, _lex = fields
            upos = _FWN_TO_UPOS.get(fwn_pos)
            if upos is None:
                continue
            translations = _meaning_terms(english_synonyms)
            if not translations:
                # A gloss is factual PWN content, but keep it as one fallback
                # meaning rather than pretending to have a dictionary translation.
                fallback = _clean_text(gloss)
                translations = [fallback] if fallback else []
            for raw_finnish in finnish_synonyms.split(" | "):
                # FinnWordNet marks approximate, broader, narrower, unconfirmed,
                # idiomatic-POS, and noted translations with XML tags.  Removing
                # those qualifiers would overstate them as direct dictionary
                # meanings, so the conservative MVP excludes qualified terms.
                if "<" in raw_finnish or ">" in raw_finnish:
                    stats["qualified_finnish_terms_excluded"] += 1
                    continue
                finnish = _clean_text(raw_finnish)
                key = normalize_lookup_key(finnish)
                if not key:
                    continue
                if any(char.isspace() for char in key):
                    stats["multiword_finnish_terms_excluded"] += 1
                    continue
                meanings[(key, upos)].update(translations)
                stats["accepted_finnish_terms"] += 1
    return meanings, stats


def _feature_signature(features: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(features, dict):
        return ()
    return tuple(sorted((str(key), str(value)) for key, value in features.items()))


def _form_sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
    return (-int(item[1]["count"]), item[0])


def _make_corpus_stats(processed_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    with processed_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                sentence = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed Phase 3 JSONL at {processed_path}:{line_number}") from exc
            original_text = sentence.get("original_text")
            source_id = sentence.get("source_id")
            dataset = sentence.get("source_dataset")
            if not isinstance(original_text, str) or not isinstance(source_id, str):
                raise ValueError(f"Missing source traceability at {processed_path}:{line_number}")
            words = [token for token in sentence.get("tokens", []) if isinstance(token, dict)]
            for token in words:
                form = token.get("form")
                lemma = token.get("lemma")
                upos = token.get("upos")
                if not isinstance(form, str) or not isinstance(lemma, str) or not isinstance(upos, str):
                    continue
                if upos == "PUNCT" or not form.strip() or not lemma.strip():
                    continue
                lemma_key = normalize_lookup_key(lemma)
                # Keep observed surface casing distinct in the index.  Lookup
                # aliases are case-folded later, but the returned corpus forms
                # must preserve what was actually annotated.
                form_key = unicodedata.normalize("NFC", form)
                key = (lemma_key, upos)
                entry = stats.setdefault(
                    key,
                    {
                        "lemma": lemma,
                        "upos": upos,
                        "frequency": 0,
                        "forms": {},
                        "examples": [],
                    },
                )
                entry["frequency"] += 1
                form_entry = entry["forms"].setdefault(
                    form_key,
                    {"form": form, "count": 0, "features": collections.Counter()},
                )
                form_entry["count"] += 1
                form_entry["features"][_feature_signature(token.get("feats"))] += 1
                entry["examples"].append(
                    {
                        "sentence": original_text,
                        "source_id": source_id,
                        "source_dataset": dataset or "unknown",
                        "form_key": form_key,
                        "lemma_key": lemma_key,
                        "word_count": int(sentence.get("word_count") or 0),
                        "has_typo": "Typo" in (token.get("misc") or {}),
                    }
                )
    return stats


def _looks_complete(sentence: str) -> bool:
    text = sentence.strip()
    if not text or text.startswith(("-", "–", "—", "...", "…")):
        return False
    if text.endswith(("...", "…", ":", ";", ",", "-", "–", "—")):
        return False
    return text[-1] in ".!?" and any(character.isalpha() for character in text)


def _select_example(entry: dict[str, Any]) -> dict[str, str] | None:
    candidates = [
        example
        for example in entry["examples"]
        if not example["has_typo"]
        and 4 <= example["word_count"] <= 15
        and _looks_complete(example["sentence"])
        and (example["form_key"] in entry["forms"] or example["lemma_key"] == normalize_lookup_key(entry["lemma"]))
    ]
    if not candidates:
        candidates = [
            example
            for example in entry["examples"]
            if not example["has_typo"] and 4 <= example["word_count"] <= 15
        ]
    if not candidates:
        candidates = [example for example in entry["examples"] if not example["has_typo"]]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda value: (value["word_count"], value["sentence"], value["source_id"]),
    )
    return {
        "sentence": selected["sentence"],
        "source_id": selected["source_id"],
        "source_dataset": selected["source_dataset"],
    }


def _entry_from_stats(
    lemma_key: str,
    upos: str,
    corpus: dict[str, Any] | None,
    meanings: Iterable[str],
) -> dict[str, Any]:
    lemma = corpus["lemma"] if corpus else lemma_key
    forms: list[dict[str, Any]] = []
    example = _select_example(corpus) if corpus else None
    if corpus:
        for _form_key, form_data in sorted(corpus["forms"].items(), key=_form_sort_key):
            signature_counts = form_data["features"]
            signatures = sorted(
                signature_counts,
                key=lambda value: (-signature_counts[value], value),
            )
            signature = signatures[0]
            forms.append(
                {
                    "form": form_data["form"],
                    "count": form_data["count"],
                    "features": dict(signature),
                    "feature_analyses": [
                        {"features": dict(value), "count": signature_counts[value]}
                        for value in signatures
                    ],
                }
            )
    lookup_keys = {lemma_key}
    lookup_keys.update(normalize_lookup_key(form["form"]) for form in forms)
    if "#" in lemma:
        lookup_keys.discard(lemma_key)
    meanings_list = sorted(set(str(value) for value in meanings if value))
    source_ids: list[str] = []
    if meanings_list:
        source_ids.append(FINNWORDNET_SOURCE.source_id)
    if corpus:
        source_ids.append(CORPUS_SOURCE.source_id)
    return {
        "lemma": lemma,
        "part_of_speech": upos,
        "meanings": meanings_list,
        "observed_forms": forms,
        "example": example,
        "usage_note": (
            "English meanings are unranked FinnWordNet sense candidates, not a context-specific translation."
            if len(meanings_list) > 1
            else None
        ),
        "source_ids": source_ids,
        "lookup_keys": sorted(lookup_keys),
        "observed_frequency": int(corpus["frequency"]) if corpus else 0,
    }


def build_vocabulary_index(
    processed_path: Path,
    finnwordnet_root: Path,
    output_path: Path,
    manifest_path: Path,
    *,
    finnwordnet_archive: Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic JSONL index and computed manifest."""

    processed_path = Path(processed_path)
    output_path = Path(output_path)
    manifest_path = Path(manifest_path)
    corpus = _make_corpus_stats(processed_path)
    meanings, finnwordnet_stats = _load_finnwordnet(Path(finnwordnet_root))
    # The MVP index is intentionally corpus-bounded.  FinnWordNet remains the
    # factual meanings/POS source, but entries with no Phase 3 observation have
    # no safe form or example to show and would make the artifact unnecessarily
    # large.  This keeps lookup aligned with the project's Finnish corpus.
    keys = set(corpus)
    entries = [
        _entry_from_stats(lemma_key, upos, corpus.get((lemma_key, upos)), meanings.get((lemma_key, upos), set()))
        for lemma_key, upos in sorted(keys)
    ]
    entries = [entry for entry in entries if entry["lookup_keys"]]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps({"schema_version": SCHEMA_VERSION, **entry}, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    source_hashes = {"processed_dataset": _sha256(processed_path)}
    if finnwordnet_archive is not None:
        source_hashes["finnwordnet_archive"] = _sha256(Path(finnwordnet_archive))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "index_version": "v1",
        "source_hashes": source_hashes,
        "sources": [FINNWORDNET_SOURCE.__dict__, CORPUS_SOURCE.__dict__],
        "counts": {
            "analysis_records": len(entries),
            "lookup_keys": len({key for entry in entries for key in entry["lookup_keys"]}),
            "corpus_analyses": len(corpus),
            "finnwordnet_analyses": len(meanings),
            "finnwordnet_overlap_analyses": sum(key in meanings for key in corpus),
            "analyses_with_meanings": sum(bool(entry["meanings"]) for entry in entries),
            "analyses_with_examples": sum(entry["example"] is not None for entry in entries),
            "observed_form_records": sum(len(entry["observed_forms"]) for entry in entries),
            "observed_feature_analyses": sum(
                len(form["feature_analyses"])
                for entry in entries
                for form in entry["observed_forms"]
            ),
            "forms_with_multiple_feature_analyses": sum(
                len(form["feature_analyses"]) > 1
                for entry in entries
                for form in entry["observed_forms"]
            ),
        },
        "finnwordnet_parsing": finnwordnet_stats,
        "quality_checks": {
            "deterministic_sorting": True,
            "unicode_preserved": True,
            "generated_forms": False,
            "meanings_from_finnwordnet_only": True,
            "qualified_translations_excluded": True,
            "morphological_ambiguity_preserved": True,
        },
    }
    manifest["output_sha256"] = _sha256(output_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


class VocabularyService:
    """Load the precomputed index once and expose safe deterministic lookup."""

    def __init__(self, index_path: Path, *, max_analyses: int = 5) -> None:
        if max_analyses < 1:
            raise ValueError("max_analyses must be positive")
        self.index_path = Path(index_path)
        self.max_analyses = max_analyses
        self._index: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        self._load()

    def _load(self) -> None:
        with self.index_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Malformed vocabulary index at {self.index_path}:{line_number}") from exc
                if entry.get("schema_version") != SCHEMA_VERSION:
                    raise ValueError(f"Unsupported vocabulary index schema at line {line_number}")
                if not entry.get("lemma") or not entry.get("part_of_speech"):
                    raise ValueError(f"Incomplete vocabulary index entry at line {line_number}")
                lookup_keys = entry.get("lookup_keys")
                if not isinstance(lookup_keys, list) or not all(
                    isinstance(key, str) and key for key in lookup_keys
                ):
                    raise ValueError(f"Invalid lookup keys at line {line_number}")
                meanings = entry.get("meanings")
                forms = entry.get("observed_forms")
                source_ids = entry.get("source_ids")
                if not isinstance(meanings, list) or not all(isinstance(value, str) for value in meanings):
                    raise ValueError(f"Invalid meanings at line {line_number}")
                if not isinstance(forms, list) or not isinstance(source_ids, list):
                    raise ValueError(f"Invalid vocabulary fields at line {line_number}")
                if not all(
                    isinstance(source_id, str) and source_id in _SOURCES_BY_ID
                    for source_id in source_ids
                ):
                    raise ValueError(f"Unknown vocabulary source at line {line_number}")
                for form in forms:
                    if not isinstance(form, dict) or not isinstance(form.get("form"), str):
                        raise ValueError(f"Invalid observed form at line {line_number}")
                    analyses = form.get("feature_analyses", [])
                    if not isinstance(analyses, list):
                        raise ValueError(f"Invalid morphology at line {line_number}")
                for key in lookup_keys:
                    self._index[key].append(entry)
        for key, entries in self._index.items():
            entries.sort(
                key=lambda entry: (
                    0 if normalize_lookup_key(entry["lemma"]) == key else 1,
                    -int(entry.get("observed_frequency", 0)),
                    entry["lemma"],
                    entry["part_of_speech"],
                )
            )

    def lookup(self, query: str) -> VocabularyResult:
        normalized = validate_query(query)
        query_key = normalize_lookup_key(normalized)
        all_candidates = self._index.get(query_key, [])
        candidates = all_candidates[: self.max_analyses]
        if not candidates:
            return VocabularyResult(query=normalized, status=VocabularyStatus.NOT_FOUND)
        analyses: list[VocabularyAnalysis] = []
        for entry in candidates:
            example_data = entry.get("example")
            example = VocabularyExample(**example_data) if example_data else None
            analyses.append(
                VocabularyAnalysis(
                    lemma=entry["lemma"],
                    part_of_speech=entry["part_of_speech"],
                    meanings=list(entry.get("meanings", [])),
                    observed_forms=[
                        ObservedForm(
                            form=form["form"],
                            count=form["count"],
                            features=dict(form.get("features", {})),
                            feature_analyses=[
                                ObservedFeatureAnalysis(**analysis)
                                for analysis in form.get(
                                    "feature_analyses",
                                    [{"features": dict(form.get("features", {})), "count": form["count"]}],
                                )
                            ],
                            matches_query=normalize_lookup_key(form["form"]) == query_key,
                        )
                        for form in entry.get("observed_forms", [])
                    ],
                    example=example,
                    usage_note=entry.get("usage_note"),
                    sources=[_SOURCES_BY_ID[source_id] for source_id in entry.get("source_ids", [])],
                )
            )
        status = VocabularyStatus.FOUND if len(analyses) == 1 else VocabularyStatus.AMBIGUOUS
        warnings = ["Multiple corpus or lexical analyses are available."] if status is VocabularyStatus.AMBIGUOUS else []
        if any(
            form.matches_query and len(form.feature_analyses) > 1
            for analysis in analyses
            for form in analysis.observed_forms
        ):
            warnings.append("The queried form has multiple observed morphological analyses.")
        if len(all_candidates) > self.max_analyses:
            warnings.append(
                f"Showing {self.max_analyses} of {len(all_candidates)} available analyses."
            )
        return VocabularyResult(query=normalized, status=status, analyses=analyses, warnings=warnings)


def _extract_archive(archive: Path) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temp = tempfile.TemporaryDirectory(prefix="finnwordnet-")
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(temp.name)
    return temp, Path(temp.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Phase 8 Finnish vocabulary index")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--finnwordnet-zip", type=Path, default=None)
    parser.add_argument("--finnwordnet-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    processed = root / "data/processed/finnish_sentences_v1.jsonl"
    output = root / "data/vocabulary/vocabulary_index_v1.jsonl"
    manifest = root / "data/vocabulary/vocabulary_manifest_v1.json"
    archive = args.finnwordnet_zip or root / "data/raw/vocabulary/FinnWordNet-2.0.zip"
    temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.finnwordnet_root:
            fwn_root = args.finnwordnet_root
            archive_for_manifest = None
        else:
            if not archive.is_file():
                raise FileNotFoundError(f"FinnWordNet archive not found: {archive}")
            temp, fwn_root = _extract_archive(archive)
            archive_for_manifest = archive
        result = build_vocabulary_index(processed, fwn_root, output, manifest, finnwordnet_archive=archive_for_manifest)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        if temp is not None:
            temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
