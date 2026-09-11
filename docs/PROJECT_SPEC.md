# FINNISH LEARNING ASSISTANT — PROJECT SPECIFICATION

## 1. Project Information

### Project Name

Finnish Learning Assistant

### Project Type

AI-powered educational web application.

### Target Users

Finnish language learners.

### Primary Goal

Help Finnish learners:

* identify grammar mistakes
* understand grammar mistakes
* correct Finnish sentences
* learn vocabulary
* track recurring mistakes
* identify weak areas
* practice through targeted exercises

---

# 2. Problem Statement

Learning Finnish grammar can be difficult because Finnish uses extensive inflection and grammatical forms.

A learner may repeatedly make similar mistakes without recognizing the underlying pattern.

A simple grammar correction tool may provide a correction but does not necessarily help the learner understand recurring weaknesses.

Therefore, this project proposes a personalized learning assistant that connects:

grammar checking
→ explanation
→ mistake history
→ weakness identification
→ targeted practice.

The goal is not merely to correct one sentence, but to create a learning feedback loop.

---

# 3. Main Product Concept

## Personalized Finnish Learning Loop

The application follows:

WRITE
↓
CHECK
↓
UNDERSTAND
↓
RECORD
↓
IDENTIFY WEAKNESS
↓
PRACTICE
↓
IMPROVE

Example:

Input:

Minä menee kouluun.

System:

Detected error:
VERB_CONJUGATION

Correction:

Minä menen kouluun.

Explanation:

The verb must agree with the first-person singular subject "minä".

The application records the mistake.

If the learner repeatedly makes the same type of mistake, the learner profile reflects this.

The exercise generator then focuses on the corresponding weakness.

---

# 4. Project Constraints

Development time:

3 weeks

Time per day:

approximately 3 hours

Total:

approximately 63 hours

Primary programming language:

Python

UI:

Streamlit

Database:

SQLite

ML:

Scikit-learn

Data processing:

Pandas

LLM:

LLM API

Development environment:

VS Code

Notebook environment:

Jupyter Notebook through VS Code

---

# 5. MVP

The MVP contains:

1. Grammar Checker
2. Grammar Error Classification
3. Sentence Correction
4. Grammar Explanation
5. Vocabulary Lookup
6. Error History
7. Learner Weakness Profile
8. Basic Exercise Generator

---

# 6. Grammar Checker

## Input

One Finnish sentence.

Example:

Minä menee kouluun.

## Output

The system should provide:

* original sentence
* whether the sentence is acceptable
* corrected sentence
* detected errors
* error type
* explanation
* confidence
* learning tip

---

# 7. Error Taxonomy

Initial taxonomy:

CASE_ERROR
VERB_CONJUGATION
NOUN_INFLECTION
WORD_ORDER
AGREEMENT
SPELLING
PLURAL
OTHER

The taxonomy is not immutable.

If data analysis demonstrates that a category is too broad or unreliable, it may be changed.

Changes must be documented.

---

# 8. Correct Sentence Behavior

If the input sentence is considered acceptable:

is_correct:

true

errors:

[]

The system should not invent a correction.

The LLM should be explicitly instructed to avoid hallucinating grammar errors.

---

# 9. LLM Output

Preferred format:

```json
{
  "original_sentence": "...",
  "is_correct": false,
  "corrected_sentence": "...",
  "errors": [
    {
      "text": "...",
      "correction": "...",
      "error_type": "...",
      "explanation": "...",
      "confidence": 0.0
    }
  ],
  "overall_explanation": "...",
  "learning_tip": "..."
}
```

The application must validate this response.

---

# 10. ML Component

The project includes a classical ML baseline.

Recommended:

TF-IDF + Logistic Regression.

Task:

Classify Finnish learner-error examples.

Input:

incorrect Finnish sentence.

Output:

error category.

Possible classes:

* CASE_ERROR
* VERB_CONJUGATION
* NOUN_INFLECTION
* WORD_ORDER
* AGREEMENT
* SPELLING
* PLURAL
* OTHER

The ML model is a baseline and educational component.

The project does not claim it is superior to LLM-based systems.

---

# 11. Dataset

Primary linguistic resources:

## UD Finnish-TDT

Use for:

* Finnish sentences
* morphology
* POS information
* dependency information
* preprocessing
* synthetic error generation
* linguistic analysis

## UD Finnish-FTB

Use for:

* grammatical examples
* grammar-oriented analysis
* exercise generation
* linguistic structures

---

# 12. Synthetic Error Dataset

Create controlled learner-error examples.

Each record must contain:

* source_sentence
* correct_sentence
* incorrect_sentence
* error_type
* correction
* generation_rule

Example:

```text
source_sentence:
Minä menen kouluun.

correct_sentence:
Minä menen kouluun.

incorrect_sentence:
Minä menee kouluun.

error_type:
VERB_CONJUGATION

correction:
menen

generation_rule:
Replace first-person singular verb form
with third-person singular form.
```

---

# 13. Data Processing

Pipeline:

Raw data
↓
Load
↓
Inspect
↓
Clean
↓
Normalize
↓
Extract relevant linguistic information
↓
Generate synthetic errors
↓
Validate examples
↓
Split dataset
↓
Train model
↓
Evaluate

---

# 14. Train/Validation/Test

Initial recommendation:

Train: 70%

Validation: 15%

Test: 15%

The split must prevent data leakage.

If several examples originate from the same source sentence:

All variants must stay within the same split.

---

# 15. Evaluation

ML metrics:

* Accuracy
* Precision
* Recall
* F1-score
* Confusion matrix

If a neural network is introduced:

* train accuracy
* validation accuracy
* test accuracy
* train loss
* validation/test loss

LLM evaluation:

* error detection correctness
* correction correctness
* classification correctness
* explanation usefulness
* false-positive rate
* structured-output validity

No fabricated results.

---

# 16. Vocabulary Feature

The user can enter a Finnish word.

The system attempts to provide:

* meaning
* lemma
* grammatical information
* example sentence

This feature should remain lightweight.

Do not build a complete dictionary.

---

# 17. Error History

The application stores:

* original sentence
* corrected sentence
* detected error
* error type
* explanation
* timestamp

The user can review previous mistakes.

---

# 18. Learner Profile

The system aggregates error frequency.

Example:

```text
CASE_ERROR          12
VERB_CONJUGATION     8
WORD_ORDER           4
SPELLING             2
```

The most frequent categories become the learner's primary weaknesses.

---

# 19. Exercise Generator

Input:

Learner's frequent error categories.

Output:

Simple targeted exercise.

Example:

Weakness:

CASE_ERROR

Exercise:

Choose the correct Finnish case.

The exercise generator should be simple enough to implement reliably within the project time.

---

# 20. UI

Technology:

Streamlit.

Suggested navigation:

* Home
* Grammar Checker
* Vocabulary
* My Mistakes
* Practice
* About

Primary interaction:

1. Enter Finnish sentence.
2. Click Check Grammar.
3. Display result.
4. Display correction.
5. Display explanation.
6. Record mistake.
7. Update learner profile.
8. Offer targeted practice.

---

# 21. Database

Use SQLite.

Minimum logical entities:

### Sentence

* id
* original_sentence
* corrected_sentence
* is_correct
* created_at

### Error

* id
* sentence_id
* error_type
* error_text
* correction
* explanation
* confidence

### Learner Profile

* error_type
* count
* last_seen

The implementation may use a simplified schema if appropriate.

---

# 22. Project Structure

```text
finnish-learning-assistant/
│
├── app.py
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
│
├── docs/
│   ├── master-prompt.md
│   ├── PROJECT_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── DATA_SOURCES.md
│   └── rubric.pdf
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
└── tests/
```

---

# 23. Security

API keys must never be committed.

Use:

.env

and:

.env.example

The real `.env` must be ignored by Git.

---

# 24. Non-Goals

The following are not part of the MVP:

* mobile application
* complex authentication
* production cloud architecture
* LLM training from scratch
* large-scale fine-tuning
* complete Finnish dictionary
* advanced user management
* payment system
* complex analytics platform
* enterprise infrastructure

---

# 25. Definition of Done

The project is considered MVP-complete when:

1. Streamlit application launches.
2. User can enter a Finnish sentence.
3. Grammar analysis works.
4. Correction works.
5. Explanation works.
6. Errors are classified.
7. Results are stored.
8. Learner weakness profile is updated.
9. Basic vocabulary lookup works.
10. Basic exercises can be generated.
11. ML baseline has been trained.
12. Train/test separation is documented.
13. Evaluation metrics are available.
14. Notebooks document the data/ML process.
15. Source code is modular.
16. API keys are protected.
17. Final demo flow works from start to finish.
18. Limitations are documented.
