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
