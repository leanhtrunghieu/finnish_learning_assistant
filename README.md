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
