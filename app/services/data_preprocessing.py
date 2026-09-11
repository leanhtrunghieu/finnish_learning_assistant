"""Strict, reproducible preprocessing for the pinned Finnish UD treebanks.

The module converts CoNLL-U sentence blocks into a sentence-level JSONL format.
It deliberately preserves surface text and Finnish annotations; it does not
perform learner-error generation, data splitting, feature extraction, or ML.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = "1.0"
PREPROCESSING_VERSION = "v1"
CONLLU_COLUMNS = (
    "ID",
    "FORM",
    "LEMMA",
    "UPOS",
    "XPOS",
    "FEATS",
    "HEAD",
    "DEPREL",
    "DEPS",
    "MISC",
)
UPOS_TAGS = {
    "ADJ",
    "ADP",
    "ADV",
    "AUX",
    "CCONJ",
    "DET",
    "INTJ",
    "NOUN",
    "NUM",
    "PART",
    "PRON",
    "PROPN",
    "PUNCT",
    "SCONJ",
    "SYM",
    "VERB",
    "X",
}
INTEGER_ID = re.compile(r"^[1-9][0-9]*$")
MWT_ID = re.compile(r"^([1-9][0-9]*)-([1-9][0-9]*)$")
EMPTY_ID = re.compile(r"^([0-9]+)\.([1-9][0-9]*)$")
DEPREL = re.compile(r"^[a-z]+(?::[a-z][a-z0-9_-]*)?$")
ATTRIBUTE_NAME = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*(?:\[[A-Za-z0-9_-]+\])?(?::[A-Za-z0-9_-]+)?$"
)

TDT_COMMIT = "bfaae13719f249573d940edda6a0d7aa8eec620f"
FTB_COMMIT = "2dd197c1f7c4b9b6d69be1e3f826162a4443af96"


class ConlluValidationError(ValueError):
    """A malformed or internally inconsistent CoNLL-U input."""


@dataclass(frozen=True)
class SourceSpec:
    """One commit-pinned CoNLL-U source file."""

    dataset: str
    commit: str
    split: str
    path: Path


@dataclass
class ParsedSource:
    """Records and actual counts parsed from one source file."""

    spec: SourceSpec
    records: list[dict[str, Any]]
    sha256: str
    size_bytes: int
    word_tokens: int
    multiword_tokens: int
    empty_nodes: int


def _context(path: Path, line_number: int, sentence_number: int) -> str:
    return f"{path} (line {line_number}, sentence {sentence_number})"


def _fail(path: Path, line_number: int, sentence_number: int, message: str) -> None:
    raise ConlluValidationError(f"{_context(path, line_number, sentence_number)}: {message}")


def _optional_text(value: str) -> str | None:
    return None if value == "_" else value


def parse_feats(
    value: str,
    *,
    path: Path = Path("<memory>"),
    line_number: int = 1,
    sentence_number: int = 1,
) -> dict[str, str]:
    """Parse and validate a CoNLL-U FEATS value into an ordered mapping."""

    if value == "_":
        return {}
    if not value:
        _fail(path, line_number, sentence_number, "FEATS must be '_' or a non-empty feature list")

    result: dict[str, str] = {}
    previous_key: str | None = None
    for item in value.split("|"):
        if item.count("=") != 1:
            _fail(path, line_number, sentence_number, f"invalid FEATS item {item!r}")
        key, feature_value = item.split("=", 1)
        if not ATTRIBUTE_NAME.fullmatch(key) or not feature_value or any(
            character in feature_value for character in "|=\t"
        ):
            _fail(path, line_number, sentence_number, f"invalid FEATS item {item!r}")
        if key in result:
            _fail(path, line_number, sentence_number, f"duplicate FEATS key {key!r}")
        if previous_key is not None and key.lower() < previous_key.lower():
            _fail(path, line_number, sentence_number, "FEATS keys are not sorted")
        result[key] = feature_value
        previous_key = key
    return result


def parse_misc(
    value: str,
    *,
    path: Path = Path("<memory>"),
    line_number: int = 1,
    sentence_number: int = 1,
) -> dict[str, str | bool]:
    """Parse the CoNLL-U MISC field while retaining valueless flags."""

    if value == "_":
        return {}
    if not value:
        _fail(path, line_number, sentence_number, "MISC must be '_' or a non-empty attribute list")

    result: dict[str, str | bool] = {}
    for item in value.split("|"):
        key, separator, attribute_value = item.partition("=")
        if not ATTRIBUTE_NAME.fullmatch(key) or (separator and not attribute_value):
            _fail(path, line_number, sentence_number, f"invalid MISC item {item!r}")
        if key in result:
            _fail(path, line_number, sentence_number, f"duplicate MISC key {key!r}")
        result[key] = attribute_value if separator else True
    return result


def make_source_id(dataset: str, source_file: str, source_sentence_id: str) -> str:
    """Build a stable provenance identifier from source coordinates."""

    if not all((dataset, source_file, source_sentence_id)):
        raise ValueError("source ID components must be non-empty")
    return f"{dataset}:{source_file}:{source_sentence_id}"


def make_leakage_group_id(original_text: str) -> str:
    """Hash NFC-normalized text without altering the stored original text."""

    normalized = unicodedata.normalize("NFC", original_text)
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def _metadata_value(comments: Sequence[tuple[int, str]], key: str) -> str | None:
    prefix = f"# {key} ="
    values = []
    for _, line in comments:
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :]
        values.append(value[1:] if value.startswith(" ") else value)
    if len(values) > 1:
        return "\0".join(values)
    return values[0] if values else None


def _row_order_key(token_id: str) -> tuple[int, int, int]:
    if match := MWT_ID.fullmatch(token_id):
        return int(match.group(1)), -1, int(match.group(2))
    if INTEGER_ID.fullmatch(token_id):
        return int(token_id), 0, 0
    if match := EMPTY_ID.fullmatch(token_id):
        return int(match.group(1)), 1, int(match.group(2))
    raise AssertionError(f"unclassified token ID: {token_id}")


def _reconstruct_text(rows: Sequence[tuple[int, list[str]]]) -> str:
    pieces: list[str] = []
    for _, fields in rows:
        if not INTEGER_ID.fullmatch(fields[0]):
            continue
        pieces.append(fields[1])
        misc = fields[9]
        if "SpaceAfter=No" not in misc.split("|"):
            pieces.append(" ")
    return "".join(pieces).rstrip(" ")


def _validate_and_build_sentence(
    *,
    spec: SourceSpec,
    sentence_number: int,
    comments: Sequence[tuple[int, str]],
    rows: Sequence[tuple[int, list[str]]],
    sentence_start_line: int,
) -> dict[str, Any]:
    path = spec.path
    if not rows:
        _fail(path, sentence_start_line, sentence_number, "sentence has no token rows")

    sent_id = _metadata_value(comments, "sent_id")
    if sent_id is not None and "\0" in sent_id:
        _fail(path, sentence_start_line, sentence_number, "sentence has multiple sent_id comments")
    if sent_id == "":
        _fail(path, sentence_start_line, sentence_number, "sent_id comment is empty")
    source_sentence_id = sent_id or f"line-{sentence_start_line}"

    text = _metadata_value(comments, "text")
    if text is not None and "\0" in text:
        _fail(path, sentence_start_line, sentence_number, "sentence has multiple text comments")
    original_text = text if text is not None else _reconstruct_text(rows)
    if not original_text:
        _fail(path, sentence_start_line, sentence_number, "sentence text is empty")

    ids = [fields[0] for _, fields in rows]
    if len(ids) != len(set(ids)):
        duplicate_ids = sorted(token_id for token_id, count in Counter(ids).items() if count > 1)
        _fail(path, sentence_start_line, sentence_number, f"duplicate token IDs: {duplicate_ids}")
    if any(_row_order_key(left) > _row_order_key(right) for left, right in zip(ids, ids[1:])):
        _fail(path, sentence_start_line, sentence_number, "token rows are not in CoNLL-U ID order")

    integer_rows = [(line, fields) for line, fields in rows if INTEGER_ID.fullmatch(fields[0])]
    mwt_rows = [(line, fields) for line, fields in rows if MWT_ID.fullmatch(fields[0])]
    empty_rows = [(line, fields) for line, fields in rows if EMPTY_ID.fullmatch(fields[0])]
    integer_ids = [int(fields[0]) for _, fields in integer_rows]
    if integer_ids != list(range(1, len(integer_ids) + 1)):
        _fail(path, sentence_start_line, sentence_number, "integer token IDs must be consecutive from 1")
    integer_id_set = set(integer_ids)

    multiword_tokens: list[dict[str, Any]] = []
    covered_mwt_ids: set[int] = set()
    for line_number, fields in mwt_rows:
        match = MWT_ID.fullmatch(fields[0])
        assert match is not None
        start, end = int(match.group(1)), int(match.group(2))
        if start >= end:
            _fail(path, line_number, sentence_number, f"invalid multiword-token range {fields[0]!r}")
        components = set(range(start, end + 1))
        if not components.issubset(integer_id_set):
            _fail(path, line_number, sentence_number, f"multiword-token range {fields[0]!r} references missing words")
        if covered_mwt_ids.intersection(components):
            _fail(path, line_number, sentence_number, f"overlapping multiword-token range {fields[0]!r}")
        if any(value != "_" for value in fields[2:9]):
            _fail(path, line_number, sentence_number, "multiword-token LEMMA through DEPS columns must be '_'")
        if not fields[1] or fields[1] == "_":
            _fail(path, line_number, sentence_number, "multiword-token FORM is missing")
        covered_mwt_ids.update(components)
        multiword_tokens.append(
            {
                "id": fields[0],
                "start": start,
                "end": end,
                "form": fields[1],
                "misc": parse_misc(fields[9], path=path, line_number=line_number, sentence_number=sentence_number),
            }
        )

    tokens: list[dict[str, Any]] = []
    for line_number, fields in integer_rows:
        token_id = int(fields[0])
        form, lemma, upos, xpos, feats, head, deprel, _deps, misc = fields[1:]
        if not form or form == "_":
            _fail(path, line_number, sentence_number, "FORM is missing for an integer-ID token")
        if upos not in UPOS_TAGS:
            _fail(path, line_number, sentence_number, f"invalid or missing UPOS {upos!r}")
        if not head.isdigit():
            _fail(path, line_number, sentence_number, f"HEAD must be an integer, got {head!r}")
        head_id = int(head)
        if head_id not in integer_id_set and head_id != 0:
            _fail(path, line_number, sentence_number, f"HEAD {head_id} does not reference a word token or root")
        if head_id == token_id:
            _fail(path, line_number, sentence_number, "token cannot be its own HEAD")
        if not DEPREL.fullmatch(deprel):
            _fail(path, line_number, sentence_number, f"invalid or missing DEPREL {deprel!r}")
        if head_id == 0 and deprel != "root":
            _fail(path, line_number, sentence_number, "a token with HEAD=0 must have DEPREL=root")
        if head_id != 0 and deprel == "root":
            _fail(path, line_number, sentence_number, "DEPREL=root requires HEAD=0")
        tokens.append(
            {
                "id": token_id,
                "form": form,
                "lemma": _optional_text(lemma),
                "upos": upos,
                "xpos": _optional_text(xpos),
                "feats": parse_feats(feats, path=path, line_number=line_number, sentence_number=sentence_number),
                "head": head_id,
                "deprel": deprel,
                "misc": parse_misc(misc, path=path, line_number=line_number, sentence_number=sentence_number),
            }
        )

    roots = [token["id"] for token in tokens if token["head"] == 0]
    if len(roots) != 1:
        _fail(path, sentence_start_line, sentence_number, f"expected exactly one dependency root, found {len(roots)}")
    heads = {token["id"]: token["head"] for token in tokens}
    for token_id in heads:
        visited: set[int] = set()
        current = token_id
        while current != 0:
            if current in visited:
                _fail(path, sentence_start_line, sentence_number, f"dependency cycle detected from token {token_id}")
            visited.add(current)
            current = heads[current]

    empty_nodes: list[dict[str, Any]] = []
    suffixes_by_base: dict[int, list[int]] = defaultdict(list)
    for line_number, fields in empty_rows:
        match = EMPTY_ID.fullmatch(fields[0])
        assert match is not None
        base, suffix = int(match.group(1)), int(match.group(2))
        if base not in integer_id_set and base != 0:
            _fail(path, line_number, sentence_number, f"empty-node ID {fields[0]!r} has an invalid base")
        if not fields[1] or fields[1] == "_":
            _fail(path, line_number, sentence_number, "empty-node FORM is missing")
        if fields[3] not in UPOS_TAGS:
            _fail(path, line_number, sentence_number, f"invalid or missing empty-node UPOS {fields[3]!r}")
        if fields[6] != "_" or fields[7] != "_":
            _fail(path, line_number, sentence_number, "empty-node HEAD and DEPREL must be '_'")
        if fields[8] == "_" or not fields[8]:
            _fail(path, line_number, sentence_number, "empty-node DEPS must be annotated")
        suffixes_by_base[base].append(suffix)
        empty_nodes.append(
            {
                "id": fields[0],
                "form": fields[1],
                "lemma": _optional_text(fields[2]),
                "upos": fields[3],
                "xpos": _optional_text(fields[4]),
                "feats": parse_feats(fields[5], path=path, line_number=line_number, sentence_number=sentence_number),
                "head": None,
                "deprel": None,
                "deps": fields[8],
                "misc": parse_misc(fields[9], path=path, line_number=line_number, sentence_number=sentence_number),
            }
        )
    for base, suffixes in suffixes_by_base.items():
        if suffixes != list(range(1, len(suffixes) + 1)):
            _fail(path, sentence_start_line, sentence_number, f"empty-node suffixes for base {base} must be consecutive from 1")

    source_id = make_source_id(spec.dataset, path.name, source_sentence_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_dataset": spec.dataset,
        "source_commit": spec.commit,
        "source_split": spec.split,
        "source_file": path.name,
        "source_sentence_id": source_sentence_id,
        "source_id": source_id,
        "leakage_group_id": make_leakage_group_id(original_text),
        "original_text": original_text,
        "word_count": len(tokens),
        "empty_node_count": len(empty_nodes),
        "multiword_tokens": multiword_tokens,
        "empty_nodes": empty_nodes,
        "tokens": tokens,
    }


def iter_conllu_sentences(spec: SourceSpec) -> Iterator[dict[str, Any]]:
    """Yield validated sentence records from one UTF-8 CoNLL-U file."""

    comments: list[tuple[int, str]] = []
    rows: list[tuple[int, list[str]]] = []
    sentence_number = 1
    sentence_start_line: int | None = None

    def finish() -> dict[str, Any] | None:
        nonlocal sentence_number, sentence_start_line
        if not rows:
            comments.clear()
            sentence_start_line = None
            return None
        start = sentence_start_line or rows[0][0]
        record = _validate_and_build_sentence(
            spec=spec,
            sentence_number=sentence_number,
            comments=comments,
            rows=rows,
            sentence_start_line=start,
        )
        comments.clear()
        rows.clear()
        sentence_number += 1
        sentence_start_line = None
        return record

    try:
        handle = spec.path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ConlluValidationError(f"cannot open CoNLL-U source {spec.path}: {exc}") from exc

    with handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if not line:
                record = finish()
                if record is not None:
                    yield record
                continue
            if sentence_start_line is None:
                sentence_start_line = line_number
            if line.startswith("#"):
                if rows:
                    _fail(spec.path, line_number, sentence_number, "comment found after token rows")
                comments.append((line_number, line))
                continue
            fields = line.split("\t")
            if len(fields) != len(CONLLU_COLUMNS):
                _fail(
                    spec.path,
                    line_number,
                    sentence_number,
                    f"expected 10 tab-separated columns, found {len(fields)}",
                )
            if any(field == "" for field in fields):
                _fail(spec.path, line_number, sentence_number, "CoNLL-U columns must not be empty; use '_' for missing values")
            token_id = fields[0]
            if not (
                INTEGER_ID.fullmatch(token_id)
                or MWT_ID.fullmatch(token_id)
                or EMPTY_ID.fullmatch(token_id)
            ):
                _fail(spec.path, line_number, sentence_number, f"invalid token ID {token_id!r}")
            rows.append((line_number, fields))

    record = finish()
    if record is not None:
        yield record


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_source(spec: SourceSpec) -> ParsedSource:
    """Parse one source and capture its actual hash and counts."""

    records = list(iter_conllu_sentences(spec))
    source_ids = [record["source_id"] for record in records]
    if len(source_ids) != len(set(source_ids)):
        duplicates = sorted(source_id for source_id, count in Counter(source_ids).items() if count > 1)
        raise ConlluValidationError(f"{spec.path}: duplicate source IDs: {duplicates[:5]}")
    return ParsedSource(
        spec=spec,
        records=records,
        sha256=_sha256_file(spec.path),
        size_bytes=spec.path.stat().st_size,
        word_tokens=sum(record["word_count"] for record in records),
        multiword_tokens=sum(len(record["multiword_tokens"]) for record in records),
        empty_nodes=sum(record["empty_node_count"] for record in records),
    )


def _repo_relative(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _missing_statistics(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float | int]]:
    token_count = sum(len(record["tokens"]) for record in records)
    result: dict[str, dict[str, float | int]] = {}
    for field in ("lemma", "xpos", "feats", "misc"):
        missing = sum(
            token[field] is None or token[field] == {}
            for record in records
            for token in record["tokens"]
        )
        result[field] = {
            "missing_count": missing,
            "missing_percent": round(100.0 * missing / token_count, 6) if token_count else 0.0,
        }
    return result


def _duplicate_statistics(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record["leakage_group_id"])].append(record)
    duplicate_groups = [group for group in groups.values() if len(group) > 1]
    return {
        "unique_text_groups": len(groups),
        "duplicate_text_groups": len(duplicate_groups),
        "records_in_duplicate_text_groups": sum(len(group) for group in duplicate_groups),
        "duplicate_records_beyond_first": sum(len(group) - 1 for group in duplicate_groups),
        "cross_dataset_duplicate_text_groups": sum(
            len({record["source_dataset"] for record in group}) > 1 for group in duplicate_groups
        ),
        "largest_duplicate_text_group": max((len(group) for group in duplicate_groups), default=1 if groups else 0),
    }


def build_manifest(
    parsed_sources: Sequence[ParsedSource],
    records: Sequence[Mapping[str, Any]],
    *,
    project_root: Path,
    output_path: Path,
    output_sha256: str,
) -> dict[str, Any]:
    """Build an audit manifest exclusively from parsed inputs and outputs."""

    input_files = []
    by_dataset: dict[str, Counter[str]] = defaultdict(Counter)
    by_split: dict[str, Counter[str]] = defaultdict(Counter)
    for source in parsed_sources:
        counts = {
            "sentences": len(source.records),
            "word_tokens": source.word_tokens,
            "multiword_tokens": source.multiword_tokens,
            "empty_nodes": source.empty_nodes,
        }
        by_dataset[source.spec.dataset].update(counts)
        by_split[f"{source.spec.dataset}:{source.spec.split}"].update(counts)
        input_files.append(
            {
                "source_dataset": source.spec.dataset,
                "source_commit": source.spec.commit,
                "source_split": source.spec.split,
                "path": _repo_relative(source.spec.path, project_root),
                "sha256": source.sha256,
                "size_bytes": source.size_bytes,
                **counts,
            }
        )

    total_sentences = len(records)
    total_words = sum(int(record["word_count"]) for record in records)
    total_mwts = sum(len(record["multiword_tokens"]) for record in records)
    total_empty = sum(int(record["empty_node_count"]) for record in records)
    source_ids = [str(record["source_id"]) for record in records]
    leakage_ids = [str(record["leakage_group_id"]) for record in records]
    return {
        "schema_version": SCHEMA_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "transformation_policy": {
            "original_text": "preserved exactly from # text; reconstructed only when absent",
            "unicode": "stored unchanged; NFC normalization is used only to hash leakage_group_id",
            "casing": "preserved",
            "punctuation": "preserved",
            "word_forms": "preserved",
            "missing_optional_annotations": "stored as null for lemma/xpos and empty mappings for feats/misc",
            "dataset_split": "upstream split retained as provenance; no project train/validation/test split created",
        },
        "source_datasets": [
            {
                "source_dataset": dataset,
                "source_commit": next(
                    source.spec.commit for source in parsed_sources if source.spec.dataset == dataset
                ),
            }
            for dataset in dict.fromkeys(source.spec.dataset for source in parsed_sources)
        ],
        "input_files": input_files,
        "input_counts": {
            "total": {
                "sentences": sum(len(source.records) for source in parsed_sources),
                "word_tokens": sum(source.word_tokens for source in parsed_sources),
                "multiword_tokens": sum(source.multiword_tokens for source in parsed_sources),
                "empty_nodes": sum(source.empty_nodes for source in parsed_sources),
            },
            "by_dataset": {key: dict(value) for key, value in by_dataset.items()},
            "by_dataset_and_split": {key: dict(value) for key, value in by_split.items()},
        },
        "output": {
            "path": _repo_relative(output_path, project_root),
            "sha256": output_sha256,
            "sentences": total_sentences,
            "word_tokens": total_words,
            "multiword_tokens": total_mwts,
            "empty_nodes": total_empty,
        },
        "missing_value_statistics": _missing_statistics(records),
        "duplicate_statistics": _duplicate_statistics(records),
        "quality_checks": {
            "all_rows_have_ten_columns": True,
            "token_ids_validated": True,
            "dependency_heads_validated": True,
            "dependency_trees_acyclic": True,
            "feats_syntax_validated": True,
            "multiword_token_ranges_validated": True,
            "sentence_ids_present_or_deterministically_fallback": True,
            "source_ids_unique": len(source_ids) == len(set(source_ids)),
            "all_records_have_source_traceability": all(source_ids),
            "all_records_have_leakage_group_id": all(leakage_ids),
            "input_output_sentence_counts_reconcile": total_sentences
            == sum(len(source.records) for source in parsed_sources),
            "input_output_word_counts_reconcile": total_words
            == sum(source.word_tokens for source in parsed_sources),
        },
    }


def write_jsonl(records: Iterable[Mapping[str, Any]], output_path: Path) -> str:
    """Write UTF-8 JSONL deterministically and return the file SHA-256."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    digest = hashlib.sha256()
    try:
        with temporary_path.open("wb") as handle:
            for record in records:
                encoded = (
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                ).encode("utf-8")
                handle.write(encoded)
                digest.update(encoded)
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def preprocess_sources(
    source_specs: Sequence[SourceSpec],
    *,
    output_path: Path,
    manifest_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Parse sources, assert global uniqueness, and write JSONL plus manifest."""

    if not source_specs:
        raise ValueError("at least one source file is required")
    parsed_sources = [parse_source(spec) for spec in source_specs]
    records = [record for source in parsed_sources for record in source.records]
    source_ids = [record["source_id"] for record in records]
    if len(source_ids) != len(set(source_ids)):
        duplicates = sorted(source_id for source_id, count in Counter(source_ids).items() if count > 1)
        raise ConlluValidationError(f"duplicate source IDs across inputs: {duplicates[:5]}")

    output_hash = write_jsonl(records, output_path)
    manifest = build_manifest(
        parsed_sources,
        records,
        project_root=project_root,
        output_path=output_path,
        output_sha256=output_hash,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    try:
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary_manifest.replace(manifest_path)
    except Exception:
        temporary_manifest.unlink(missing_ok=True)
        raise
    return manifest


def _git_head(repository: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"could not read Git commit for {repository}: {exc}") from exc
    return completed.stdout.strip()


def default_source_specs(project_root: Path) -> list[SourceSpec]:
    """Return the six approved sources after verifying pinned repository commits."""

    raw_root = project_root / "data" / "raw"
    definitions = (
        ("UD_Finnish-TDT", "finnish_tdt", TDT_COMMIT, "fi_tdt"),
        ("UD_Finnish-FTB", "finnish_ftb", FTB_COMMIT, "fi_ftb"),
    )
    specs: list[SourceSpec] = []
    for dataset, directory_name, expected_commit, file_prefix in definitions:
        repository = raw_root / directory_name
        actual_commit = _git_head(repository)
        if actual_commit != expected_commit:
            raise RuntimeError(
                f"{repository} is at {actual_commit}, expected approved commit {expected_commit}"
            )
        for split in ("train", "dev", "test"):
            path = repository / f"{file_prefix}-ud-{split}.conllu"
            if not path.is_file():
                raise FileNotFoundError(f"approved source file not found: {path}")
            specs.append(SourceSpec(dataset, actual_commit, split, path))
    return specs


def run_default_preprocessing(project_root: Path) -> dict[str, Any]:
    """Run the approved Phase 3 pipeline for the six pinned raw files."""

    project_root = project_root.resolve()
    processed_root = project_root / "data" / "processed"
    return preprocess_sources(
        default_source_specs(project_root),
        output_path=processed_root / "finnish_sentences_v1.jsonl",
        manifest_path=processed_root / "preprocessing_manifest_v1.json",
        project_root=project_root,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: current directory)",
    )
    args = parser.parse_args()
    manifest = run_default_preprocessing(args.project_root)
    print(json.dumps(manifest["output"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
