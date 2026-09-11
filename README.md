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
