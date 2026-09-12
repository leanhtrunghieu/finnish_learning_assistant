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
