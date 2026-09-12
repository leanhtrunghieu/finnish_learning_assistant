# FINNISH LEARNING ASSISTANT — DATA SOURCES

## 1. Purpose

This document defines the datasets and linguistic resources used by the Finnish Learning Assistant.

The project must distinguish between:

1. source linguistic data
2. processed data
3. synthetic learner-error data
4. evaluation data

Do not mix these datasets without documenting the transformation.

---

# 2. Primary Dataset — UD Finnish-TDT

Name:

Universal Dependencies Finnish-TDT

Underlying resource:

Turku Dependency Treebank (TDT)

Repository:

https://github.com/UniversalDependencies/UD_Finnish-TDT

Official treebank information:

https://universaldependencies.org/treebanks/fi_tdt/index.html

License:

CC BY-SA 4.0

The current repository metadata reports:

* training set: 12,217 sentences
* development data: 716 + 648 sentences
* test set: 1,555 sentences

The repository describes Finnish-TDT as a broad-coverage Finnish dependency treebank covering multiple genres, including news, wiki, blog, legal, fiction and grammar examples.

It contains linguistic annotations such as:

* lemmas
* UPOS
* XPOS
* morphological features
* dependency relations

---

# 3. Purpose of Finnish-TDT

Finnish-TDT is the primary linguistic source for:

* Finnish sentence analysis
* preprocessing
* morphology analysis
* POS analysis
* dependency analysis
* correct Finnish sentence examples
* synthetic error generation
* ML experimentation

It should NOT be treated as a learner-error corpus.

It contains correctly annotated Finnish linguistic material, not a complete collection of Finnish learner mistakes.

---

# 4. Finnish-TDT License Handling

License:

CC BY-SA 4.0

The project should provide appropriate attribution when using the dataset.

Do not remove original attribution information.

If processed or derived data is redistributed, check the applicable license requirements.

Do not assume that every text source contained in any Finnish dataset has identical copyright conditions.

---

# 5. Secondary Dataset — UD Finnish-FTB

Name:

Universal Dependencies Finnish-FTB

Official page:

https://universaldependencies.org/treebanks/fi_ftb/index.html

Repository:

https://github.com/UniversalDependencies/UD_Finnish-FTB

License:

CC BY 4.0

Finnish-FTB is based on FinnTreeBank 1.

The official UD description states that it consists of manually annotated grammatical examples from VISK (The Web Version of the Large Grammar of Finnish).

The UD version was converted from the native annotation model and manually revised.

---

# 6. Purpose of Finnish-FTB

Use Finnish-FTB primarily for:

* grammatical examples
* Finnish grammatical structures
* grammar-oriented analysis
* exercise design
* checking grammatical patterns

It is particularly useful because its content is grammar-example oriented.

---

# 7. Important Data Distinction

Finnish-TDT and Finnish-FTB are not learner-error datasets.

They are linguistic resources.

Therefore:

```text
Finnish-TDT / Finnish-FTB
        ↓
Correct Finnish examples
        ↓
Controlled transformation
        ↓
Synthetic learner-error dataset
```

The synthetic dataset is a project-generated dataset.

---

# 8. Synthetic Learner-Error Dataset

The project needs examples containing learner-style errors.

Because the project has a limited development period, create a controlled synthetic dataset from correct Finnish sentences.

Do not describe this synthetic dataset as authentic learner writing.

It should be described as:

"controlled synthetic Finnish learner-error data generated from Finnish linguistic resources."

---

# 9. Synthetic Dataset Schema

Recommended CSV/Parquet schema:

```text
id
source_dataset
source_sentence_id
source_sentence
correct_sentence
incorrect_sentence
error_type
correction
generation_rule
```

Optional:

```text
difficulty
metadata
```

---

# 10. Error Types

Initial taxonomy:

```text
CASE_ERROR
VERB_CONJUGATION
NOUN_INFLECTION
WORD_ORDER
AGREEMENT
SPELLING
PLURAL
OTHER
```

The taxonomy can be revised after inspecting the dataset.

---

# 11. Synthetic Error Generation Rules

Errors must be linguistically motivated.

Do not generate random corruption.

## Example 1 — Verb Conjugation

Correct:

```text
Minä menen kouluun.
```

Synthetic error:

```text
Minä menee kouluun.
```

Label:

```text
VERB_CONJUGATION
```

Correction:

```text
menen
```

Rule:

Change first-person singular verb form to an inappropriate third-person singular form.

---

## Example 2 — Case Error

Correct:

```text
Menen kouluun.
```

Synthetic error:

```text
Menen koulu.
```

Label:

```text
CASE_ERROR
```

The exact generation rule must be linguistically validated before being used in the dataset.

Do not assume that every substitution of one Finnish case for another is grammatically incorrect in every context.

---

## Example 3 — Number Error

Correct:

```text
Minulla on kaksi koiraa.
```

Synthetic error:

```text
Minulla on kaksi koira.
```

Label:

```text
PLURAL
```

Again, generated examples must be validated.

---

# 12. Validation of Synthetic Errors

Every generation rule should be manually checked.

The generator should not automatically assume that the transformation produced a real grammar error.

Recommended workflow:

```text
Generate
 ↓
Automatic validation
 ↓
Sample manual inspection
 ↓
Remove invalid examples
 ↓
Store final dataset
```

Keep the generation rule in the dataset so examples can be traced back to their source.

---

# 13. Data Leakage Prevention

This is critical.

Suppose:

```text
Source sentence A
   ↓
Variant A1
Variant A2
Variant A3
```

Do NOT do:

```text
A1 → train
A2 → test
A3 → validation
```

This could cause data leakage.

Instead:

```text
Source sentence A
   ↓
A1, A2, A3
   ↓
same dataset split
```

Use source sentence/group identifiers.

---

# 14. Dataset Splitting

Recommended:

```text
Train       70%
Validation  15%
Test        15%
```

The split should be group-aware where multiple examples come from the same source sentence.

---

# 15. Test Set

The test set must not be modified after model development begins except through a documented process.

The test set should represent the error categories used by the classifier.

Include examples from multiple categories.

---

# 16. Evaluation Dataset

Create:

```text
data/evaluation/
```

Possible files:

```text
grammar_evaluation.csv
llm_evaluation.csv
ml_test.csv
```

The evaluation set should contain manually reviewed examples.

Recommended categories:

1. Correct sentence
2. Single error
3. Multiple errors
4. Case error
5. Verb conjugation
6. Noun inflection
7. Word order
8. Agreement
9. Spelling
10. Plural

---

# 17. LLM Evaluation Dataset

The LLM evaluation dataset should be manually reviewed.

For each sentence record:

```text
sentence
expected_is_correct
expected_error_types
expected_correction
notes
```

Possible evaluation:

```text
Expected:
VERB_CONJUGATION

LLM:
VERB_CONJUGATION

→ Correct classification
```

The evaluation must not be designed to make the LLM look artificially good.

---

# 18. Other Potential Finnish Learner Corpora

Potential future sources may include Finnish learner corpora such as:

* ICLFI
* CEFLING

However, these resources may have access restrictions, privacy conditions, or other usage requirements.

They should NOT be treated as guaranteed project dependencies.

If access is unavailable within the 3-week development period:

Do not block the project.

Proceed with:

UD Finnish-TDT
+
UD Finnish-FTB
+
controlled synthetic errors.

If learner corpora are later obtained legally and appropriately, they can be used as an additional evaluation or research resource.

---

# 19. Out-of-Domain Evaluation

UD Finnish-OOD may be considered for robustness experiments.

Repository:

https://github.com/UniversalDependencies/UD_Finnish-OOD

The dataset's annotations are licensed CC BY-SA 4.0, while the underlying texts come from various Internet sources that may have different copyright owners.

Therefore:

Do not automatically redistribute or reuse the underlying text outside the permitted conditions.

For this project, Finnish-OOD is optional and should not be required for MVP completion.

---

# 20. Data Directory

Recommended structure:

```text
data/
│
├── raw/
│   ├── finnish_tdt/
│   └── finnish_ftb/
│
├── processed/
│   └── finnish_sentences/
│
├── errors/
│   ├── synthetic_errors.csv
│   └── validated_errors.csv
│
└── evaluation/
    ├── ml_test.csv
    ├── grammar_evaluation.csv
    └── llm_evaluation.csv
```

---

# 21. Data Pipeline

Complete pipeline:

```text
UD Finnish-TDT
       │
       ├─────────────┐
       │             │
       ▼             ▼
Preprocessing     Analysis
       │
       ▼
Correct sentences
       │
       ▼
Synthetic error generation
       │
       ▼
Validation
       │
       ▼
Error dataset
       │
       ▼
Group-aware train/validation/test split
       │
       ├──────────────┐
       ▼              ▼
     ML model       Evaluation
```

Finnish-FTB can separately support:

```text
Finnish-FTB
    ↓
Grammar examples
    ↓
Exercise design
    ↓
Grammar analysis
```

---

# 22. Data Quality Requirements

Before training:

Check:

* missing values
* duplicate sentences
* malformed records
* invalid labels
* class imbalance
* invalid synthetic corrections
* duplicate source groups
* train/test leakage

Produce basic statistics.

Example:

```text
Total examples:
Training:
Validation:
Test:

CASE_ERROR:
VERB_CONJUGATION:
...

Class distribution:
...
```

---

# 23. Reproducibility

Synthetic error generation should be reproducible.

Use a fixed random seed where randomness is involved.

Record:

* dataset version
* generation version
* random seed
* generation rules
* preprocessing version

Example:

```text
random_seed = 42
```

---

# 24. Data Licensing Rules

Before adding any new dataset:

1. Identify the original source.
2. Identify the license.
3. Check whether commercial/non-commercial restrictions exist.
4. Check redistribution conditions.
5. Record the license in this document.
6. Preserve attribution.
7. Do not scrape content merely because it is publicly accessible.

Never assume:

"Public on the Internet = free to use."

---

# 25. Current Recommended Data Strategy

For the 3-week MVP:

PRIMARY:

UD Finnish-TDT

SECONDARY:

UD Finnish-FTB

GENERATED:

Controlled synthetic learner-error dataset

OPTIONAL:

Finnish-OOD

POTENTIAL FUTURE:

ICLFI / CEFLING if access and usage conditions permit.

---

# 26. Data Strategy Decision

The project must not depend on restricted learner corpora for MVP completion.

The minimum viable data pipeline is:

```text
Finnish-TDT
      +
Finnish-FTB
      ↓
Preprocessing
      ↓
Correct Finnish examples
      ↓
Synthetic learner errors
      ↓
Validation
      ↓
Train / Validation / Test
      ↓
ML baseline
      ↓
Evaluation
```

This approach is realistic within the project's approximately 63-hour development constraint.

---

# 27. Phase 2 Acquisition Snapshot

The Phase 2 exploration uses depth-1 clones of the official repositories, acquired on 2026-09-10:

| Dataset | Raw directory | Checked-out commit | CoNLL-U files |
|---|---|---|---|
| UD Finnish-TDT | `data/raw/finnish_tdt/` | `bfaae13719f249573d940edda6a0d7aa8eec620f` | `fi_tdt-ud-train.conllu`, `fi_tdt-ud-dev.conllu`, `fi_tdt-ud-test.conllu` |
| UD Finnish-FTB | `data/raw/finnish_ftb/` | `2dd197c1f7c4b9b6d69be1e3f826162a4443af96` | `fi_ftb-ud-train.conllu`, `fi_ftb-ud-dev.conllu`, `fi_ftb-ud-test.conllu` |

To reacquire the same raw inputs in a fresh checkout, clone each official
repository and then detach at the recorded commit. A plain depth-1 clone by
itself is not reproducible because the repository tip can move:

```powershell
git clone https://github.com/UniversalDependencies/UD_Finnish-TDT.git data/raw/finnish_tdt
git -C data/raw/finnish_tdt checkout --detach bfaae13719f249573d940edda6a0d7aa8eec620f

git clone https://github.com/UniversalDependencies/UD_Finnish-FTB.git data/raw/finnish_ftb
git -C data/raw/finnish_ftb checkout --detach 2dd197c1f7c4b9b6d69be1e3f826162a4443af96
```

After acquisition, `git -C data/raw/finnish_tdt status --short` and
`git -C data/raw/finnish_ftb status --short` should both produce no output.

The upstream `README` and `LICENSE` files are retained in each raw directory. The raw CoNLL-U files are read-only inputs for `notebooks/01_dataset_exploration.ipynb`; derived tables must be written under `data/processed/`, `data/errors/`, or `data/evaluation/` in later phases. The repository's existing `.gitignore` intentionally excludes `data/raw/*`, so redistribution of the source text should be handled deliberately and in accordance with the TDT CC BY-SA 4.0 and FTB CC BY 4.0 (or LGPLv3+) terms and the upstream text-source notices.

The FTB README contains a stale human-readable word total (159,612); the checked-out `stats.xml` and direct CoNLL-U inspection agree on 159,625 syntactic words. Use the machine-readable metadata and parsed files for reproducible counts, and retain this discrepancy as a data-quality note.

---

# 28. Phase 3 Preprocessing Snapshot

Phase 3 reads only the six CoNLL-U files and commits listed above. Run the
reusable pipeline from the repository root with:

```powershell
python -m app.services.data_preprocessing --project-root .
```

The command verifies each raw repository commit before processing and writes:

```text
data/processed/finnish_sentences_v1.jsonl
data/processed/preprocessing_manifest_v1.json
```

The JSONL contains one UTF-8 JSON object per source sentence. Each record keeps
the source dataset, commit, upstream split, file, sentence ID, a deterministic
`source_id`, unchanged `original_text`, and token-level Finnish annotations.
Integer word IDs, multiword-token ranges, and decimal empty-node IDs remain
distinct. Optional source underscores become `null` for lemma/XPOS and empty
mappings for FEATS/MISC; they do not cause rows to be discarded. FEATS are
parsed without limiting them to a small preselected key list, so annotations
needed for later case, number, person, tense, mood, voice, and related rules are
retained.

The transformation deliberately does not lowercase, remove punctuation, stem,
change word forms, or normalize Finnish grammar. NFC normalization is used only
to calculate the deterministic `leakage_group_id`; `original_text` itself is
preserved. Duplicate sources are retained for provenance. Records with equal
NFC-normalized text share a leakage group, including duplicates across TDT and
FTB. Future generated variants must copy this identifier and future project
splits must keep each group intact.

The manifest is generated from the actual run. It records both source commits,
SHA-256 and size for every input, per-file/dataset/split counts, output count and
hash, missing-value statistics, duplicate-group statistics, MWT and empty-node
counts, and quality-check results. At the approved commits the reconciled total
is 33,859 sentences and 361,818 integer-ID word tokens. These totals are audit
expectations and are not hard-coded into the parser.

`notebooks/02_preprocessing.ipynb` executes the same service module and presents
the schema, examples, reconciliation, missing values, duplicates, special ID
handling, and Phase 4 hand-off. No synthetic learner errors, final project data
split, features, labels, or models are created in Phase 3.

---

# 29. Phase 4 Synthetic Learner-Error Snapshot

Phase 4 reads `data/processed/finnish_sentences_v1.jsonl` without modifying it.
The generator first verifies that file against the Phase 3 manifest, then uses
the sentence text, token spans, morphology, dependencies, and provenance through:

```powershell
python -m app.services.error_generation --project-root .
```

The generated artifacts are:

```text
data/errors/synthetic_errors_v1.jsonl
data/errors/error_generation_manifest_v1.json
```

The approved initial taxonomy is deliberately narrow. `CASE_ERROR` changes the
case of an agreeing attributive adjective while keeping number and degree;
`VERB_CONJUGATION` changes the person and/or number of a finite active indicative
verb with one overt, matching nominative personal-pronoun subject; and
`AGREEMENT` changes the number of an agreeing attributive adjective while
keeping case and degree. Every replacement is a surface form observed elsewhere
in the Phase 3 corpus for the same lemma and compatible retained features.
Generated morphology is never guessed.

TDT explicitly records `Degree=Pos` on ordinary positive adjectives, whereas
FTB normally leaves positive degree unmarked and marks comparative/superlative
forms explicitly. The generator treats both positive conventions as eligible
within their own complete feature signatures. Analyses carrying `Degree=Cmp`,
`Degree=Sup`, `NumType`, `Style`, or other unsafe extra features remain excluded.

Each record contains one exact character-span replacement and its known inverse
correction. Prefix and suffix text are checked byte-for-text equality at the
Python string level, so unrelated casing, punctuation, whitespace, and Finnish
characters remain untouched. Sentences with multiword-token rows or empty nodes
are excluded from version 1 because one-to-one editable surface alignment is
not guaranteed. Other exclusions include unsafe morphology, missing reliable
dependency evidence, token-span alignment failure, and the configured 3--30 word
length range.

The default deterministic configuration uses seed 42, caps each class at 1,000
examples, allows no more than one example of a class per leakage group, two
total variants per leakage group, and 50 examples per lemma/class. The three
classes are balanced after selection. The manifest reports eligible candidates,
every selection/exclusion count, validation failures, duplicate checks, the
final output SHA-256, and a deterministic sample of 20 examples per category for
manual review. These are computed run results rather than target constants.

All variants inherit the Phase 3 `source_id` and `leakage_group_id`. Phase 4 does
not split the data: Phase 5 must use `leakage_group_id` as an indivisible group
when assigning train, validation, and test partitions. Synthetic data remains a
controlled proxy rather than proof that every example matches a naturally
occurring learner error; the notebook therefore exposes category-stratified
examples for human inspection and documents that limitation.

Phase 4 review also identified residual shortcut risk after harmonizing the
treebanks' positive-adjective annotation convention. The final 3,000 records
contain 1,363 FTB and 1,637 TDT sources, but the FTB share is higher for
`VERB_CONJUGATION` (659/1,000) than for `CASE_ERROR` (365/1,000) or `AGREEMENT`
(339/1,000). Verb examples are also shorter on average because the rule requires
an overt personal-pronoun subject. Phase 5 must not interpret high classification
accuracy as direct evidence of general Finnish grammar understanding. It should
stratify the grouped split by error label and source dataset where feasible,
remove formatting-only whitespace cues in its feature view, inspect learned
features, and report performance by source dataset as a sensitivity check.

---

# 30. Phase 5 Evaluation Snapshot

Run the deterministic baseline with:

```powershell
python -m app.services.ml_training --project-root .
```

The Phase 4 JSONL remains unchanged. Phase 5 writes the exact record objects into
`data/evaluation/train_v1.jsonl`, `validation_v1.jsonl`, and `test_v1.jsonl`.
`data/evaluation/ml_split_manifest_v1.json` records the Phase 4 data and manifest
hashes, seed 42, the grouped-fold algorithm, actual proportions, per-split class
and source distributions, output hashes, and zero-overlap evidence. Test
predictions are stored separately in `ml_test_predictions_v1.jsonl` for audited
error analysis.

Every `leakage_group_id` is assigned to exactly one partition. Approximate
label/source stratification is secondary to that constraint. Feature vocabulary
and inverse-document-frequency values are fitted only from the training JSONL.
The saved model metadata in `models/error_classifier_v1_metadata.json` links the
input hash, split-manifest hash, full experiment configuration, metrics, model
artifact hash, and limitations. Re-running with the same files and configuration
reproduces the split and predictions.

Licensing and provenance remain inherited from Phase 2--4 source records. The
evaluation files are derived synthetic data, not naturally sampled Finnish
learner writing, and must not be used to claim real-world diagnostic coverage.

---

# 31. Phase 6 Grammar Evaluation Cases

Phase 6 adds `data/evaluation/grammar_cases_v1.jsonl`, a manually curated set of
40 Finnish service cases. It contains correct standard sentences, six supported
single-error categories, multiple-error inputs, colloquial-tolerant examples,
incomplete/ambiguous inputs, and style-only false-positive controls. Expected
corrections and error categories are human-authored; they are not generated by
the LLM being evaluated.

The case file is an evaluation aid rather than a new linguistic source. No
learner corpus is introduced, and the Phase 3--5 datasets remain unchanged.
Systematic scoring of this set belongs to the later evaluation phase; Phase 6
provides mocked unit tests and opt-in live smoke tests for the service itself.

---

# 32. Phase 8 Vocabulary Sources

Phase 8 uses two legally documented sources and keeps their roles separate.

## FinnWordNet 2.0

* **Official archive:** https://www.kielipankki.fi/download/FinnWordNet/v2.0/FinnWordNet-2.0.zip
* **Official README:** https://www.kielipankki.fi/download/FinnWordNet/v2.0/README.txt
* **Role:** Finnish lemma/synset mappings, lexical part of speech, and English
  translations/glosses from the downloadable TSV/WordNet data.
* **License:** Princeton WordNet license plus Creative Commons Attribution 3.0
  for the University of Helsinki translations. The Princeton copyright notice
  and University of Helsinki attribution must be preserved.
* **Limitations:** a WordNet is a lexical-semantic resource, not a learner
  dictionary or complete Finnish morphology generator. Multiword expressions
  and sense distinctions are retained only where the Phase 8 one-token index
  can represent them safely. English meanings are aggregated, unranked sense
  candidates rather than context-disambiguated translations. Finnish entries
  tagged as approximate, broader, narrower, unconfirmed, or otherwise qualified
  are excluded instead of having their caution markers stripped.

## UD Finnish-TDT and UD Finnish-FTB through Phase 3

* **TDT:** https://universaldependencies.org/treebanks/fi_tdt/index.html
* **FTB:** https://universaldependencies.org/treebanks/fi_ftb/index.html
* **Role:** observed surface forms, lemmas, Universal POS tags, FEATS,
  frequencies, and selected short corpus examples from the validated Phase 3
  JSONL.
* **Licenses:** TDT CC BY-SA 4.0; FTB CC BY 4.0, as recorded in the Phase 2
  acquisition snapshot.
* **Limitations:** UD corpora are annotated examples, not dictionaries. They do
  not provide authoritative English definitions, and observed forms are not a
  complete paradigm. The index therefore reports only forms actually observed
  in the corpus and keeps source IDs for examples. When one surface form has
  several observed UD feature signatures, the index preserves every signature
  and its count rather than presenting one analysis as uniquely correct.

The resulting `data/vocabulary/vocabulary_index_v1.jsonl` is a deterministic,
corpus-bounded derived artifact. `data/vocabulary/vocabulary_manifest_v1.json`
records the Phase 3 and FinnWordNet hashes, source metadata, counts, and quality
checks. FinnWordNet archive acquisition is reproducible from the official URL;
the downloaded archive remains under ignored `data/raw/vocabulary/`. Attribution
is also copied to `data/vocabulary/ATTRIBUTION.md`.

Kotus Nykysuomen sanalista, Omorfi, and FreeDict were reviewed as possible
future sources but are not Phase 8 dependencies: Kotus provides headwords and
inflection codes without definitions, Omorfi adds GPLv3/HFST integration scope,
and FreeDict requires checking each dictionary's TEI license before use. No
restricted online dictionary is scraped.
