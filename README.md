# Finnish Learning Assistant

The Finnish Learning Assistant is an AI-powered educational application for Finnish language learners. Its planned learning loop connects grammar feedback with error history, recurring weakness detection, and targeted practice.

## Phase 1 status

Phase 1 provides the project foundation only:

- Streamlit application shell
- Environment-backed configuration
- Console logging and startup error handling
- Modular application folders
- Basic pytest structure

Grammar checking, preprocessing, machine learning, LLM calls, persistence, vocabulary, and exercises belong to later phases.

## Phase 2 status

Phase 2 acquires the official UD Finnish-TDT and UD Finnish-FTB repositories under `data/raw/` and documents their structure in [`notebooks/01_dataset_exploration.ipynb`](notebooks/01_dataset_exploration.ipynb). The notebook is exploratory only: it does not create processed data, synthetic learner errors, splits, or models. Raw files and upstream attribution/licensing notices are retained unchanged; acquisition provenance is recorded in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

## Phase 3 status

Phase 3 converts the six commit-pinned CoNLL-U files into
`data/processed/finnish_sentences_v1.jsonl` using the reusable strict parser in
`app/services/data_preprocessing.py`. Each sentence retains source provenance,
unchanged Finnish text, integer-ID word annotations, multiword-token ranges,
and decimal-ID empty nodes. `data/processed/preprocessing_manifest_v1.json`
records input hashes and counts, output counts/hash, missing values, duplicates,
and validation results. `notebooks/02_preprocessing.ipynb` presents the complete
workflow and audit.

No learner errors, project data split, feature extraction, or model training is
performed in this phase.

## Phase 4 status

Phase 4 creates a controlled synthetic learner-error dataset from the validated
Phase 3 sentences. The reusable generator in `app/services/error_generation.py`
uses only three narrow, annotation-supported categories: adjective case
mismatch (`CASE_ERROR`), finite-verb person/number mismatch
(`VERB_CONJUGATION`), and adjective number mismatch (`AGREEMENT`). Replacement
forms must already occur in the Phase 3 corpus with compatible morphology; the
generator does not synthesize Finnish inflections. Positive adjective degree is
accepted both when explicitly marked by TDT and when left unmarked by FTB;
comparatives, superlatives, ordinals, and other extra analyses remain excluded.

Each example changes exactly one aligned token span, records its correction and
rule, and copies `source_id` and `leakage_group_id`. Phase 4 does not create the
final train/validation/test split or train a model.

## Technology plan

- Python
- Streamlit
- Pandas and scikit-learn for later data and ML work
- SQLite for later persistence
- An LLM API for later grammar analysis
- Jupyter Notebook through VS Code for later data and model work

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install the project dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` when local configuration is needed. Never commit `.env` or API keys.

## Explore the Phase 2 datasets

Acquire the commit-pinned raw datasets by following the commands in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md#27-phase-2-acquisition-snapshot).
Then open `notebooks/01_dataset_exploration.ipynb` in VS Code, select the
project `.venv` Python kernel, and use **Run All**. Cells are ordered and the
notebook reads the raw files without writing derived data.

## Run Phase 3 preprocessing

After acquiring the exact raw commits documented in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md#27-phase-2-acquisition-snapshot), run:

```powershell
python -m app.services.data_preprocessing --project-root .
```

The command verifies the checked-out commits, validates all CoNLL-U rows, and
recreates both versioned files under `data/processed/`. It fails with source
file, line, and sentence context rather than repairing malformed input.

The JSONL schema uses one object per sentence. Provenance is held in
`source_dataset`, `source_commit`, `source_split`, `source_file`,
`source_sentence_id`, and deterministic `source_id` fields. Normal word tokens
retain their surface form, lemma, UPOS/XPOS, parsed morphology, dependency head
and relation, and MISC attributes. Missing optional lemma/XPOS values are
`null`; missing FEATS/MISC values are `{}`.

`leakage_group_id` is the SHA-256 of NFC-normalized `original_text`. The text
stored in the record is not normalized or lowercased. Duplicate source records
remain in the output, but identical normalized texts share the grouping ID so
all future synthetic variants can be kept together during leakage-safe
splitting.

For the presentation-oriented audit, open `notebooks/02_preprocessing.ipynb`
with the project environment and use **Run All**.

## Run Phase 4 error generation

After producing the Phase 3 files, run:

```powershell
python -m app.services.error_generation --project-root .
```

The command verifies the Phase 3 JSONL against its manifest, generates the
versioned JSONL and manifest under `data/errors/`, validates every record, and
fails rather than guessing when a rule is not safe. The fixed default seed is
42. Sampling is balanced at 1,000 examples per class, with at most two variants
per leakage group and 50 per lemma/class.

`data/errors/synthetic_errors_v1.jsonl` stores one UTF-8 JSON object per
single-error example. Its core fields include `synthetic_id`, source provenance,
`leakage_group_id`, correct and incorrect sentences, `error_type`, exact
character `error_span`, `correction`, `generation_rule`, `changed_token_id`, and
auditable rule metadata. `data/errors/error_generation_manifest_v1.json` stores
input/output hashes, configuration, computed candidate/rejection counts,
class distribution, duplicate checks, and a deterministic manual-review sample.

Open `notebooks/03_error_generation.ipynb` and use **Run All** for the
presentation-oriented audit and representative examples.

## Run the Phase 5 ML baseline

After producing the approved Phase 4 dataset, run:

```powershell
python -m app.services.ml_training --project-root .
```

The command verifies the Phase 4 input hash; creates deterministic, grouped
train/validation/test JSONL files under `data/evaluation/`; fits a character
3--5-gram TF-IDF plus Logistic Regression pipeline using training text only;
and writes the complete fitted pipeline to `models/error_classifier_v1.joblib`.
The split manifest and model metadata contain computed distributions, pairwise
leakage checks, metrics, confusion matrices, hashes, and interpretation evidence.

All records sharing `leakage_group_id` remain in one split. The fixed seed is
42 and the approximate split is 70/15/15; group isolation takes precedence over
exact percentages. The target is the three-class synthetic `error_type`, given
`incorrect_sentence`. This educational baseline does not detect arbitrary
real-world Finnish grammar errors.

Open `notebooks/04_ml_baseline.ipynb` and use **Run All** to reproduce the
experiment and view per-class metrics, the final test confusion matrix, learned
character features, shortcut checks, and representative misclassifications.

## Run the Phase 6 grammar service

Phase 6 adds a provider-isolated grammar service without connecting it to the
Streamlit UI or learner database. Copy `.env.example` to `.env`, set
`LLM_API_KEY` and `LLM_MODEL`, and use a compatible JSON-chat endpoint in
`LLM_API_BASE_URL`. Never commit the real key.

For a configured provider, a basic smoke check is:

```powershell
python -m app.services.grammar_service "Minä menee kouluun."
```

The service validates the Finnish input, loads the versioned prompt, requests
structured JSON through `llm_service.py`, retries one transient or malformed
response, and returns a typed grammar result. It supports standard Finnish by
default and an explicit `--colloquial-tolerant` mode. The supported learner
taxonomy is `CASE_ERROR`, `VERB_CONJUGATION`, `NOUN_INFLECTION`, `WORD_ORDER`,
`AGREEMENT`, `SPELLING`, and `OTHER`.

Phase 6 does not save history, update profiles, generate exercises, or integrate
the full UI. `data/evaluation/grammar_cases_v1.jsonl` is a manually curated
functional/evaluation case set; systematic evaluation remains a later phase.

## Run the application

```powershell
streamlit run app.py --server.address localhost
```

The Phase 1 screen displays the project name and a short description. Later phases will add the learning workflow described in the project documents.
Use an explicit non-local address only when intentionally demonstrating the app on a trusted network.

## Project structure

```text
app.py
app/
├── ui/          # Streamlit presentation components
├── services/    # Business services added in later phases
├── models/      # Application data models added in later phases
├── prompts/     # Versioned LLM prompts added in later phases
└── utils/       # Configuration, logging, and shared errors
data/            # Raw, processed, error, and evaluation data
database/        # SQLite artifacts added in a later phase
models/          # Trained model artifacts added in a later phase
notebooks/       # Data and ML notebooks added in later phases
tests/           # Automated tests
```

The complete product scope and architecture are documented in `docs/`.
