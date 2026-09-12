# FINNISH LEARNING ASSISTANT — SYSTEM ARCHITECTURE

## 1. Architecture Overview

The system uses a hybrid architecture combining:

* Streamlit
* Python
* Finnish linguistic resources
* classical machine learning
* LLM API
* SQLite
* rule-based processing

High-level flow:

```text
                    ┌────────────────────┐
                    │       USER         │
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │   STREAMLIT UI     │
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │ INPUT PREPROCESSOR │
                    └─────────┬──────────┘
                              │
                              ▼
              ┌──────────────────────────────┐
              │ FINNISH NLP / ML COMPONENTS │
              └──────────────┬───────────────┘
                             │
                ┌────────────┴─────────────┐
                │                          │
                ▼                          ▼
       ┌─────────────────┐       ┌─────────────────┐
       │ ML CLASSIFIER   │       │    LLM API      │
       └────────┬────────┘       └────────┬────────┘
                │                         │
                └───────────┬─────────────┘
                            ▼
                  ┌─────────────────────┐
                  │ ANALYSIS RESULT     │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │    SQLITE DB        │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ LEARNER PROFILE     │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ EXERCISE GENERATOR  │
                  └──────────┬──────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │   STREAMLIT UI  │
                    └────────────────┘
```

---

# 2. Architectural Principles

The system should follow these principles:

## Simplicity

Use the simplest technology that solves the problem.

## Modularity

Separate:

* UI
* business logic
* AI/ML
* database
* prompts
* utilities

## Explainability

Every AI output should be understandable to the learner.

## Testability

Core components should be testable independently.

## Replaceability

The LLM provider should be replaceable without rewriting the entire application.

---

# 3. Application Layers

## Layer 1 — UI

Technology:

Streamlit.

Responsibilities:

* receive user input
* display results
* show history
* show profile
* show exercises
* handle navigation

The UI should not contain complex AI logic.

---

# 4. Service Layer

Location:

```text
app/services/
```

Responsibilities:

* grammar checking
* vocabulary lookup
* LLM communication
* error processing
* learner profile calculation
* exercise generation

Possible modules:

```text
grammar_service.py
vocabulary_service.py
llm_service.py
profile_service.py
exercise_service.py
```

---

# 5. Model Layer

Location:

```text
app/models/
```

Contains application data structures.

Possible classes:

```text
GrammarResult
GrammarError
VocabularyResult
Exercise
LearnerProfile
```

Use Python dataclasses or Pydantic if appropriate.

Do not introduce a framework unnecessarily.

---

# 6. Prompt Layer

Location:

```text
app/prompts/
```

Possible files:

```text
grammar_checker_prompt.txt
vocabulary_prompt.txt
exercise_generator_prompt.txt
```

Prompts must not be hardcoded throughout the application.

---

# 7. Utility Layer

Location:

```text
app/utils/
```

Possible responsibilities:

* text normalization
* JSON validation
* logging
* configuration
* helper functions

---

# 8. Input Processing

Input pipeline:

```text
User text
   ↓
Whitespace normalization
   ↓
Unicode normalization if needed
   ↓
Basic validation
   ↓
Sentence length validation
   ↓
Finnish NLP analysis
```

Do not aggressively normalize Finnish text in ways that alter linguistic meaning.

---

# 9. Grammar Analysis Architecture

Grammar analysis should use a hybrid strategy.

```text
Finnish sentence
       │
       ▼
Preprocessing
       │
       ├───────────────┐
       ▼               ▼
Finnish NLP        LLM analysis
       │               │
       │               │
       └───────┬───────┘
               ▼
        Result validation
               │
               ▼
        Structured result
```

The LLM provides contextual reasoning.

The NLP/ML components provide structured linguistic information and a baseline.

---

# 10. ML Baseline Architecture

Recommended:

```text
Synthetic Error Dataset
        ↓
Text preprocessing
        ↓
Train/Test Split
        ↓
TF-IDF
        ↓
Logistic Regression
        ↓
Error Classification
        ↓
Evaluation
```

Pipeline:

```text
X_train
   ↓
TF-IDF fit_transform

X_test
   ↓
TF-IDF transform

X_train
   ↓
Logistic Regression
   ↓
Prediction
   ↓
Metrics
```

Important:

The TF-IDF vectorizer must be fitted only on training data.

Do not fit preprocessing components on the test set.

---

# 11. Data Leakage Prevention

Data leakage must be explicitly prevented.

Example:

Source sentence:

```text
Minä menen kouluun.
```

Generated variants:

```text
Minä menee kouluun.
Minä menin kouluun.
Minä mennä kouluun.
```

These variants must not be distributed across train and test.

Otherwise the evaluation may be artificially inflated.

Use a source-group identifier if necessary.

---

# 12. LLM Architecture

The LLM should receive a controlled prompt.

Example conceptual flow:

```text
Sentence
   ↓
System Prompt
   +
Error Taxonomy
   +
Output Schema
   ↓
LLM API
   ↓
JSON
   ↓
Schema Validation
   ↓
Application Result
```

The LLM should not directly write to the database.

Instead:

```text
LLM
 ↓
validated result
 ↓
service layer
 ↓
database
```

---

# 13. LLM Response Validation

Expected response:

```json
{
  "original_sentence": "...",
  "is_correct": false,
  "corrected_sentence": "...",
  "errors": [],
  "overall_explanation": "...",
  "learning_tip": "..."
}
```

Validation process:

```text
LLM response
      ↓
JSON parse
      ↓
Schema validation
      ↓
Required fields check
      ↓
Confidence validation
      ↓
Application object
```

If validation fails:

```text
Invalid response
      ↓
controlled error handling
      ↓
retry or user-friendly fallback
```

Never allow malformed LLM output to crash the UI.

---

# 14. Database Architecture

Use SQLite.

Conceptual schema:

```text
sentences
----------------
id
original_sentence
corrected_sentence
is_correct
created_at


errors
----------------
id
sentence_id
error_type
error_text
correction
explanation
confidence


learner_profile
----------------
error_type
count
last_seen
```

Relationship:

```text
sentences
    │
    │ 1:N
    ▼
 errors
```

The learner profile can be calculated from the errors table or maintained incrementally.

---

# 15. Learner Profile

Example:

```text
Learner Profile

CASE_ERROR          12
VERB_CONJUGATION     8
WORD_ORDER           4
SPELLING             2
```

The profile service should determine:

```text
Most frequent error
        ↓
Primary weakness
        ↓
Exercise topic
```

---

# 16. Exercise Generator

Input:

```text
Learner profile
```

Example:

```text
CASE_ERROR: 12
VERB_CONJUGATION: 8
```

Select:

```text
CASE_ERROR
```

Generate:

```text
Targeted exercise
```

The exercise should contain:

* question
* options/input
* expected answer
* explanation
* error category

---

# 17. Vocabulary Architecture

Vocabulary lookup can use:

```text
User word
   ↓
Normalization
   ↓
Dictionary/LLM/resource lookup
   ↓
Structured vocabulary result
   ↓
UI
```

The feature must remain independent of the grammar checker.

---

# 18. UI Architecture

Suggested Streamlit pages:

```text
Home
Grammar Checker
Vocabulary
My Mistakes
Practice
About
```

The most important page is Grammar Checker.

Recommended layout:

```text
┌─────────────────────────────────────────┐
│ Finnish Learning Assistant              │
├─────────────────────────────────────────┤
│                                         │
│ Enter Finnish sentence:                 │
│                                         │
│ [ Minä menee kouluun.                 ] │
│                                         │
│              [ Check Grammar ]          │
│                                         │
├─────────────────────────────────────────┤
│ Result                                  │
│                                         │
│ ❌ Grammar issue                        │
│                                         │
│ Corrected:                              │
│ Minä menen kouluun.                     │
│                                         │
│ Error: VERB_CONJUGATION                 │
│                                         │
│ Explanation: ...                        │
│                                         │
├─────────────────────────────────────────┤
│ Your recurring weaknesses               │
│                                         │
│ VERB_CONJUGATION: 8                     │
│ CASE_ERROR: 5                           │
└─────────────────────────────────────────┘
```

The actual UI design can be improved later.

---

# 19. Error Handling

The application must gracefully handle:

* empty input
* invalid input
* API timeout
* API rate limit
* API authentication failure
* malformed JSON
* database errors
* missing environment variables

Example:

```text
API unavailable

The grammar service is temporarily unavailable.
Please try again later.
```

Do not expose raw stack traces to the user.

---

# 20. Configuration

Use environment variables.

Example:

```text
LLM_API_KEY
LLM_MODEL
```

Use:

```text
python-dotenv
```

Never hardcode secrets.

---

# 21. Testing Architecture

Tests should be separated by responsibility.

```text
tests/
├── test_preprocessing.py
├── test_error_generation.py
├── test_ml_model.py
├── test_llm_parser.py
├── test_database.py
├── test_profile.py
└── test_exercise.py
```

Prioritize testing the deterministic components.

---

# 22. Notebook Architecture

Notebooks:

```text
notebooks/
├── 01_dataset_exploration.ipynb
├── 02_preprocessing.ipynb
├── 03_error_generation.ipynb
├── 04_ml_baseline.ipynb
└── 05_evaluation.ipynb
```

Purpose:

### 01

Understand the dataset.

### 02

Build preprocessing.

### 03

Generate controlled synthetic errors.

### 04

Train the baseline model.

### 05

Evaluate the model.

The notebooks should contain explanations, not only code.

---

# 23. Folder Architecture

```text
finnish-learning-assistant/
│
├── app.py
│
├── app/
│   ├── ui/
│   ├── services/
│   ├── models/
│   ├── prompts/
│   └── utils/
│
├── data/
│   ├── raw/
│   ├── processed/
│   ├── errors/
│   └── evaluation/
│
├── notebooks/
│
├── database/
│
├── models/
│
├── tests/
│
├── docs/
│   ├── master-prompt.md
│   ├── PROJECT_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── DATA_SOURCES.md
│   └── rubric.pdf
│
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

# 24. Dependency Direction

Prefer:

```text
UI
 ↓
Services
 ↓
Models / Utilities
 ↓
External systems
```

Avoid:

```text
UI
 ↓
Database
 ↓
LLM
 ↓
Random utility
 ↓
UI
```

The service layer should coordinate the application.

---

# 24.1 Phase 5 ML Baseline Snapshot

Phase 5 is isolated in `app/services/ml_training.py`. It reads the immutable
Phase 4 JSONL and validates its SHA-256 against the generation manifest. A
deterministic `StratifiedGroupKFold` assignment uses `leakage_group_id` as the
indivisible group and `error_type|source_dataset` as the approximate
stratification key. Twenty folds are aggregated as 14 training, 3 validation,
and 3 test folds. Pairwise group intersections are required to be empty.

The fitted artifact is one scikit-learn `Pipeline`:

```text
format-only feature normalization
  -> character-within-word TF-IDF (3--5 grams)
  -> multinomial Logistic Regression
```

Only the training split is passed to `Pipeline.fit`, so validation and test
sentences cannot influence vocabulary or IDF values. Normalization applies NFC,
collapses whitespace, and removes spaces before common punctuation only in the
model's feature view; source and split JSONL records are unchanged. The complete
pipeline is saved at `models/error_classifier_v1.joblib` and can therefore be
loaded without separately fitted feature state.

The test partition is evaluated once after the baseline configuration is fixed.
Metadata records accuracy, macro precision/recall/F1, probability log loss,
per-class results, confusion matrices, top-weighted features, source sensitivity,
and representative predictions. These results characterize three synthetic
labels and are not evidence of general Finnish grammar checking capability.

---

# 24.2 Phase 6 LLM Grammar Service

Phase 6 keeps grammar analysis behind two service boundaries:

```text
GrammarService
    ↓
LLMClient protocol
    ↓
OpenAI-compatible JSON provider adapter
    ↓
validated GrammarResult
```

`grammar_service.py` owns Finnish input validation, prompt loading, language
mode, one repair attempt, and cross-field result validation. `llm_service.py`
owns environment configuration, HTTP transport, provider status mapping,
bounded retries, and response-envelope extraction. The provider adapter is not
called from Streamlit UI code.

The typed models in `app/models/grammar.py` use dataclasses and explicit
validation because Pydantic is not an available project dependency. They enforce
the seven learner-oriented categories, confidence bounds, original-sentence
identity, correct/incorrect consistency, multiple-error limits, and conservative
uncertainty handling. The versioned prompt is stored in
`app/prompts/grammar_checker_prompt.txt`.

The Phase 5 classifier remains an experimental comparison artifact. It is not
used to decide whether a learner sentence is correct, to override the LLM, or to
act as a production fallback. Phase 6 deliberately does not add persistence,
profiles, vocabulary, exercises, or full UI integration.

---

# 24.3 Phase 7 Learner History and Weakness Profile

Phase 7 persists validated grammar results locally with Python's built-in
`sqlite3`. The database service is intentionally small and independent of the
LLM provider:

```text
GrammarResult
    ↓
DatabaseService
    ├── grammar_checks (one row per analysis)
    └── grammar_errors (zero or more rows per check)
    ↓
ProfileService
    └── deterministic counts, percentages, and primary weakness
```

The default runtime path is `database/finnish_learning_assistant.db`, and the
existing `*.db`, `*.sqlite`, and `*.sqlite3` ignore rules prevent local learner
history from being committed. The MVP associates rows with a lightweight
`learner_id` such as `demo_user`; authentication and account management are
out of scope.

`grammar_checks` stores the original/corrected sentence, correctness flag,
explanation, learning tip, language mode, analysis status, uncertainty note,
schema version, learner ID, and UTC timestamp. `grammar_errors` stores the
canonical Phase 6 error type, text, correction, explanation, confidence, and
its ordered position under the parent check. Foreign keys and an explicit
`PRAGMA foreign_keys = ON` enforce the one-to-many relationship.

Saving a result uses one transaction: the parent check and every child error
are committed together or rolled back together. Correct checks are retained
for history but produce no child errors. The profile is calculated from actual
stored error rows rather than duplicated counters. Counts are ranked by
descending frequency and then error-type name; percentages are based on total
complete-analysis errors. `UNCERTAIN` analyses remain retrievable but are not
included in weakness aggregation, and stored confidence is not used as an
uncalibrated weight.

Phase 7 provides service-level persistence and profile calculation only. The
polished Streamlit history/profile views, exercises, and authentication remain
later-phase work; vocabulary is implemented separately in Phase 8.

---

## 24.4 Phase 8 Vocabulary Service

Phase 8 adds an independent, service-level vocabulary subsystem. It is
deliberately corpus-bounded rather than a complete Finnish dictionary:

```text
FinnWordNet 2.0 (meanings/POS)
             +
Phase 3 UD corpus (observed forms/features/examples)
             ↓
deterministic JSONL vocabulary index
             ↓
VocabularyService.lookup(query)
             ↓
typed VocabularyResult
```

`app/services/vocabulary_service.py` builds and loads
`data/vocabulary/vocabulary_index_v1.jsonl`. FinnWordNet contributes factual
English lexical meanings and POS; the processed TDT/FTB corpus contributes only
observed Finnish forms, UD morphology, corpus frequency, and selected short
examples. The index manifest records source hashes and computed counts. Inputs
are NFC-normalized and case-folded only for lookup keys; the original query and
surface forms remain unchanged. A query with several analyses returns
`ambiguous`, an absent query returns `not_found`, and no complete Finnish
inflection paradigm is generated.

Each observed form retains its most frequent UD feature signature in `features`
for a compact default view and every observed signature/count in
`feature_analyses`, so syncretic or annotation-dependent morphology is not
silently collapsed. Query-matching forms are marked at runtime. FinnWordNet
translations carrying approximate, broader, narrower, unconfirmed, or other
qualifier tags are conservatively excluded. Remaining meanings are explicitly
documented as unranked sense candidates, not context-disambiguated definitions.

The factual source and license details are recorded in
`data/vocabulary/ATTRIBUTION.md` and `docs/DATA_SOURCES.md`. Phase 8 does not
call the Phase 6 LLM, store vocabulary history, or add a Streamlit page; those
boundaries keep lookup deterministic and leave later UI work independent.

---

## 24.5 Phase 9 Personalized Exercise Service

Phase 9 completes the service-level learning loop without adding a Practice
page or a second provider client:

```text
ProfileService
      ↓
deterministic supported weakness selection
      ↓
ExerciseService
      ↓
shared LLMClient / LLMService
      ↓
strict exercise validation
      ↓
Exercise + deterministic answer checking
```

`ExerciseService` consumes the actual Phase 7 `LearnerProfile`; it never asks
the LLM to infer a learner's weakness. Weaknesses are ranked by count
descending and canonical error-type name ascending. The first supported
category is selected, or the caller may explicitly request a supported topic.
With no supported history, the service returns a controlled target-unavailable
error rather than fabricating a default weakness. `WORD_ORDER` and `OTHER` are
deferred from automatic generation because Finnish word order and open-ended
categories can admit multiple valid answers.

The MVP uses one exercise type, `MULTIPLE_CHOICE`, and one difficulty,
`BASIC`. The provider receives only the target category, type, difficulty, and
the versioned prompt; learner identity and full history are not sent. The
provider response contains no provider-controlled ID or metadata. The service
computes a stable SHA-256 exercise ID, requires four unique options with the
correct answer appearing exactly once, and returns a typed `Exercise` model.
Answer checking compares an option label, index, or option text
deterministically after NFC normalization and boundary trimming; it never calls
the LLM to grade an answer. One bounded repair request is allowed for malformed
exercise JSON, while authentication, timeout, configuration, and provider
failures become safe `ExerciseServiceError` messages.

Phase 9 intentionally does not persist exercise attempts, couple generation to
the Phase 8 vocabulary index, add recommendation ML, or build the final
Streamlit Practice UI. Generated exercises remain LLM-produced teaching
material and require later manual linguistic evaluation.

---

# 24.6 Phase 10 Streamlit Integration

Phase 10 keeps Streamlit as a thin presentation layer over the existing
services. `app.py` owns configuration, sidebar navigation, and page routing;
the page modules under `app/ui/` render state and call the grammar, database,
profile, vocabulary, and exercise services. Provider-specific calls remain
behind `GrammarService`, `ExerciseService`, and the shared LLM transport.

Stable resources are constructed through `app/ui/services.py` and cached with
`st.cache_resource`: the initialized SQLite service, shared LLM service,
grammar/exercise services, and the static vocabulary index. Learner-specific
history and profiles are queried on each page render rather than cached
indefinitely.

Grammar and exercise provider calls happen only after explicit form/button
actions. The grammar page saves one validated result in the submitted action
and stores its check ID in `st.session_state`; rendering a later rerun does not
save again. The Practice page stores the current validated exercise and answer
result in session state, so selecting an option or checking an answer does not
generate a replacement exercise. The MVP uses `demo_user`, has no
authentication, and reports provider/configuration failures as concise UI
messages without exposing tracebacks or secrets.

The six pages are Home, Grammar Checker, Vocabulary, My Mistakes (including the
weakness profile), Practice, and About. The Phase 5 classifier remains a
comparison artifact and is not placed in the end-user grammar flow. Phase 10
does not alter prior datasets, models, services, or add Phase 11 evaluation.

---

# 25. External API Isolation

Do not call the LLM API directly from Streamlit UI code.

Prefer:

```text
Streamlit
   ↓
grammar_service
   ↓
llm_service
   ↓
LLM API
```

This makes the provider replaceable and easier to test.

---

# 26. Final System Flow

The complete MVP should work as:

```text
USER
 ↓
Streamlit
 ↓
Sentence validation
 ↓
Preprocessing
 ↓
Finnish NLP / ML analysis
 ↓
LLM grammar analysis
 ↓
JSON validation
 ↓
Grammar result
 ↓
Save to SQLite
 ↓
Update learner profile
 ↓
Determine weakness
 ↓
Generate exercise
 ↓
Display result
```

This flow is the central architecture of the project.
