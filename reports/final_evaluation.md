# Final Evaluation - Phase 11

Evaluation version: `v1`  
Evaluation date: `2026-09-13T02:23:42Z`  
Git commit evaluated: `81646ba03a6123407e39d08e5c68c082d7040ff8`  
Verdict: **READY FOR PHASE 12**

## 1. Evaluation scope

Feature scope was frozen at the approved Phase 10 commit. This report evaluates grammar, the Phase 5 baseline, vocabulary, profiles/personalization, exercises, and the integrated application separately. No Phase 12 presentation work or major product feature was added.

## 2. Methodology

- Grammar: 40 frozen, human-authored cases; positive class = a sentence contains at least one grammar error.
- Vocabulary: 16 manually source-audited lookup cases.
- Profiles: 6 temporary-database histories and 4 target-selection profiles.
- Exercises: 20 requests, four for each of five supported categories.
- Explanation and exercise judgments use an AI-assisted qualitative linguistic review under the named reviewer identity; no human/native-teacher review is claimed, and qualitative ratings remain separate from structural validity.
- Missing outputs remain failures; no failed record was removed to improve a score.

## 3. Grammar results

Provider: `openai_compatible`; model: `gpt-5.6-luna`; temperature: `0.0`.

Provider responses were received for **40/40** attempts. Valid typed results: **39/40** (97.50%). Provider transport/HTTP failures: **0**; malformed/invalid provider outputs: **1**.

### Detection metrics

Metrics cover 39/40 cases with an actual prediction. Accuracy: **0.949**; precision: **0.944**; recall: **0.944**; F1: **0.944**.

Confusion counts: **TP=17**, **TN=20**, **FP=1**, **FN=1**. Matrix `[[TN, FP], [FN, TP]]`: `[[20, 1], [1, 17]]`.

### False-positive rate

False positives: **1** / **22 frozen valid sentences** = **4.55%**. Prediction-conditioned rate: **1/21 = 4.76%**; 1 valid case had no validated prediction and is not misreported as a true negative.

### Error-type classification

Single-error category exact match: **83.33%** over 12/12 cases. Macro precision/recall/F1: **1.000 / 0.833 / 0.889**.

| Category | Dataset support | Evaluated support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| AGREEMENT | 2 | 2 | 1.000 | 1.000 | 1.000 |
| CASE_ERROR | 2 | 2 | 1.000 | 1.000 | 1.000 |
| NOUN_INFLECTION | 2 | 2 | 1.000 | 1.000 | 1.000 |
| SPELLING | 2 | 2 | 1.000 | 1.000 | 1.000 |
| VERB_CONJUGATION | 2 | 2 | 1.000 | 0.500 | 0.667 |
| WORD_ORDER | 2 | 2 | 1.000 | 0.500 | 0.667 |

Each single-error category has only two frozen examples, so per-class and macro results are descriptive rather than robust population estimates.

Multiple-error set scoring covers 6/6 cases without forcing a single label. Set exact match: **66.67%**. Micro precision/recall/F1: **0.900 / 0.818 / 0.857**. Macro precision/recall/F1: **0.917 / 0.833 / 0.861**.

### Corrections and explanations

Correction outcomes across the frozen set: `{'exact_match': 17, 'acceptable_alternative': 0, 'incorrect_correction': 1, 'not_applicable': 21, 'no_output': 1}`. Among the 18 reviewable erroneous outputs, exact match rate: **94.44%**; accepted including reviewed alternatives: **94.44%**. No AI-assisted correction-acceptability override was used.

AI-assisted qualitative explanation reviews completed: **39/39**; non-reviewable because no validated output: **1**. Scale: 1-3. These ratings are AI-assisted judgments under the named reviewer identity, not a human/native-teacher assessment or objective linguistic truth.

| Criterion | Score 1 | Score 2 | Score 3 | Mean | Score 3 | Score 1 or 2 |
|---|---:|---:|---:|---:|---:|---:|
| grammatical correctness | 4 | 5 | 30 | 2.667 | 76.92% | 23.08% |
| relevance | 1 | 2 | 36 | 2.897 | 92.31% | 7.69% |
| clarity | 0 | 3 | 36 | 2.923 | 92.31% | 7.69% |
| learner usefulness | 4 | 3 | 32 | 2.718 | 82.05% | 17.95% |

Recurring supported issues include subject-verb agreement, attributive-versus-predicative analysis, numeral-plus-singular-partitive morphology, connegative terminology, total-object terminology, and colloquial-register handling. The case IDs and review notes are retained in the machine-readable failure analysis.

## 4. ML baseline verification

All reproducibility checks passed: **True**. Split counts are `{'train': 2101, 'validation': 450, 'test': 449}` and recomputed group intersections are `{'train_validation': 0, 'train_test': 0, 'validation_test': 0}`.

| Split | Accuracy | Macro F1 | Log loss | Recomputed match |
|---|---:|---:|---:|---|
| train | 0.933 | 0.933 | 0.509 | True |
| validation | 0.691 | 0.687 | 0.705 | True |
| test | 0.710 | 0.709 | 0.704 | True |

The baseline classifies three controlled synthetic error categories from an already-incorrect sentence. It does not decide whether arbitrary Finnish is correct, so its scores are not directly comparable with grammar-checker metrics. Character suffixes, source imbalance, sentence length, and an approximately 0.224 train-test macro-F1 gap show shortcut/generalization risk.

Phase 11 found and fixed one blocking artifact-loading defect: the frozen Phase 5 pickle referred to its custom normalizer through `__main__`. The loader now supplies a narrowly scoped compatibility alias; the model, split, and prediction artifacts were not changed or retrained, and all stored metrics were reproduced after the fix.

## 5. Vocabulary results

| Measure | Passed | Evaluated | Rate |
|---|---:|---:|---:|
| lookup_status_correct | 16 | 16 | 100.00% |
| lemma_correct | 16 | 16 | 100.00% |
| pos_correct | 16 | 16 | 100.00% |
| morphology_correct | 15 | 15 | 100.00% |
| meaning_correct_or_availability_expected | 15 | 15 | 100.00% |
| example_relevance | 15 | 15 | 100.00% |
| provenance_available | 15 | 15 | 100.00% |
| ambiguity_behavior_correct | 8 | 8 | 100.00% |
| unknown_word_behavior_correct | 1 | 1 | 100.00% |

Index statistics: 40624 analysis records, 93547 lookup keys, 39506 normalized lemmas, and 5313 ambiguous keys. These describe the bounded artifact, not Finnish dictionary coverage.

## 6. Profile and personalization results

Profile histories: **6/6 PASS**. Personalization profiles: **4/4 PASS**. Counts, percentages, ranking, ties, isolation, and zero-history behavior were checked exactly.

No-history behavior is deliberate: automatic selection fails safely and the learner must explicitly choose one of the supported topics.

## 7. Exercise results

Generated: **20/20**; provider failures: **0**. Schema-valid: **20/20** (100.00%). Structurally valid over all requests: **20/20** (100.00%). AI-assisted qualitative linguistic reviews: **20**; pending: **0**; not reviewable because no output: **0**.

Structural validity checks taxonomy, type, question, four unique options, exactly one correct-answer occurrence, and explanation presence. The separate AI-assisted qualitative rubric covers relevance, clarity, ambiguity, answer correctness, distractors, explanation correctness, and unintended Finnish errors.

| Category | Requested | Generated | Structurally valid | Qualitatively reviewed |
|---|---:|---:|---:|---:|
| CASE_ERROR | 4 | 4 | 4 | 4 |
| VERB_CONJUGATION | 4 | 4 | 4 | 4 |
| NOUN_INFLECTION | 4 | 4 | 4 | 4 |
| AGREEMENT | 4 | 4 | 4 | 4 |
| SPELLING | 4 | 4 | 4 | 4 |

| Criterion | PASS | PARTIAL | FAIL | PASS rate | Non-PASS rate |
|---|---:|---:|---:|---:|---:|
| target relevance | 20 | 0 | 0 | 100.00% | 0.00% |
| question clarity | 19 | 1 | 0 | 95.00% | 5.00% |
| unambiguous | 19 | 1 | 0 | 95.00% | 5.00% |
| answer correctness | 19 | 0 | 1 | 95.00% | 5.00% |
| distractor plausibility | 11 | 8 | 1 | 55.00% | 45.00% |
| explanation correctness | 17 | 2 | 1 | 85.00% | 15.00% |
| no unrelated errors | 20 | 0 | 0 | 100.00% | 0.00% |

Structural validity was 100%, but linguistic/pedagogical validity was not: `noun_inflection_03` stores an incorrect answer and explanation, while nine exercises have weak distractors and two explanations oversimplify Finnish object terminology.

## 8. End-to-end validation

Executed scenarios: **12/12 PASS**. Real Streamlit process smoke: **PASS** with health response `ok`.

Rerun evidence shows one grammar submit caused one analysis and one insertion; result rendering did not repeat either; selecting/checking an answer preserved the exercise and did not regenerate it.

## 9. Performance and reliability

Warmed local vocabulary lookups: n=30, median=0.063 ms, p95=0.289 ms.

Profile retrieval: n=30, median=10.681 ms, p95=12.526 ms.

Grammar primary-attempt latency: median=1873.815 ms; exercise-attempt latency: median=1427.348 ms. External API latency depends on the provider and network.

Repeatability was not rerun during this resumed 40+20 live evaluation. API cost was not formally measured because token/accounting data were unavailable.

## 10. Failure analysis

Observed failure taxonomy: `{'exercise:ambiguous_answer': 1, 'exercise:incorrect_answer': 1, 'exercise:incorrect_explanation': 1, 'exercise:oversimplified_rule': 2, 'exercise:unclear_question': 1, 'exercise:weak_distractor': 9, 'grammar:analysis_status_mismatch': 1, 'grammar:extra_category': 3, 'grammar:false_negative': 1, 'grammar:false_positive': 1, 'grammar:incorrect_correction': 1, 'grammar:invalid_provider_output': 1, 'grammar:missing_expected_category': 4, 'grammar:wrong_category': 1, 'ml:misclassified_synthetic_test_example': 130}`.

Provider, schema, and objective scoring failures are retained rather than filtered from the raw artifacts. The Phase 5 test confusion matrix contains genuine misclassifications and remains unchanged.

Qualitative grammar findings (AI-assisted review):

- subject-verb agreement false acceptance: `single_verb_02`.
- attributive versus predicative terminology: `correct_07`.
- numeral plus singular-partitive morphology: `single_noun_01, single_noun_02`.
- connegative form mislabeled as an infinitive: `single_order_02`.
- oversimplified total-object case terminology: `correct_04, multiple_04`.
- colloquial Finnish treated too prescriptively: `uncertain_04`.

Exercise qualitative review recorded 10 exercises with at least one PARTIAL or FAIL rating. The machine-readable records retain every rating, failure reason, and reviewer note.

## 11. Limitations

- Grammar explanation quality and exercise linguistic quality use AI-assisted qualitative linguistic review; these ratings are not a human/native-teacher assessment, and automatic structure and correctness metrics do not replace them.
- External LLM behavior is nondeterministic and may change with provider or model updates even when the prompt and dataset hashes remain fixed.
- The Phase 5 baseline uses controlled synthetic examples from only three categories; its scores do not establish real-learner grammar performance.
- Phase 5 character n-grams show suffix, source, and sentence-length shortcut risk, including a substantial train-test performance gap.
- The vocabulary index is bounded by observed UD forms and FinnWordNet overlap; it is neither a complete dictionary nor a complete morphology system.
- Vocabulary meanings are unranked sense candidates and are not context-disambiguated translations.
- The AI-assisted exercise review found one incorrect stored answer/explanation and weak distractors in nine of 20 exercises despite 100% structural validity.
- SQLite and the demo learner identity are suitable for a local MVP, not authenticated multi-user production use.
- The 40-case grammar set, 16-case vocabulary set, and 20-exercise sample are deliberately small and manually auditable, not population-wide estimates.
- The optional 12-request repeatability sample was not rerun because this resumed task was limited to the remaining 40 grammar and 20 exercise attempts.
- The approved transport retry bound is recorded as one, but per-request transport retry usage is not persisted; exact retry utilization cannot be reconstructed from the evaluation rows.
- Automated UI checks do not establish audience acceptance, presentation confidence, or oral explanation quality.

## 12. Rubric evidence matrix

| Criterion | Implementation evidence | Evaluation evidence | Status | Notes |
|---|---|---|---|---|
| Data transformation before training | Phase 3 parser, processed JSONL, manifest, and notebook 02. | Phase 3 output hash and 33,859-record manifest remained intact. | SATISFIED | Original Finnish text is preserved; model-only normalization is documented. |
| Separate train and test evaluation | Grouped train/validation/test JSONL files and Phase 5 split manifest. | All pairwise leakage-group intersections were recomputed as zero. | SATISFIED | Source-group isolation takes priority over exact split proportions. |
| Accuracy and loss for train and test | Phase 5 metadata stores train, validation, and test metrics. | Saved-pipeline metrics were recomputed, including classification log loss. | SATISFIED | Log loss is classification log loss, not a neural training curve. |
| Acceptable model accuracy or prompted LLM functionality | Saved Logistic Regression pipeline and validated LLM service boundaries. | All 40 live grammar attempts were recorded: 39 validated outputs, 1 invalid provider output, and 0 transport/HTTP failures. | SATISFIED | ML and LLM tasks are different and are not compared as one accuracy score. |
| Real-world/community problem | Project specification addresses recurring Finnish-learning errors. | End-to-end checks exercise the complete learning feedback loop. | SATISFIED | Audience impact still requires live feedback evidence. |
| Original and creative idea | Grammar feedback is connected to local history, ranked weaknesses, and practice. | Controlled persistence/profile/personalization scenarios validate that connection. | PARTIAL | Originality is partly a qualitative judgment for assessors. |
| Technologies beyond curriculum via documentation | UD, FinnWordNet, Streamlit, SQLite, scikit-learn, and an isolated LLM API. | Artifacts, licenses, service tests, and reproducibility commands are documented. | SATISFIED | Presentation must still demonstrate the student's understanding. |
| Logical and aesthetic application/UI library use | Six-page Streamlit UI with centralized routing and learner-facing labels. | All pages rendered and the real Streamlit health endpoint returned ok. | SATISFIED | Automated checks establish function and flow, not audience taste. |
| Audience acceptance | No audience-feedback artifact exists in Phase 11. | Cannot be established through source code or automated evaluation. | REQUIRES LIVE PRESENTATION | Requires live presentation/audience evidence outside Phase 11. |
| Confident presentation and audience interaction | Not a software implementation criterion. | Not observable in this repository. | REQUIRES LIVE PRESENTATION | Requires live presentation evidence outside Phase 11. |
| Self-evaluation after audience/judge feedback | Phase reviews and this failure/limitations audit provide technical self-evaluation. | No post-audience or post-judge feedback exists yet. | REQUIRES LIVE PRESENTATION | The feedback-specific portion requires live assessment evidence. |
| Logical application demo flow | Write -> check -> history/profile -> practice is implemented. | End-to-end scenarios validate each transition with isolated state. | REQUIRES LIVE PRESENTATION | A live demo performance is not proven by code alone. |
| Combine feature explanation with demo | About page and notebooks explain architecture and feature roles. | No live presentation was observed. | REQUIRES LIVE PRESENTATION | Requires live presentation evidence outside Phase 11. |
| Problem analysis and justified AI solution | Project docs distinguish deterministic, ML, linguistic-resource, and LLM roles. | Component-specific evaluation avoids claiming AI where deterministic logic is used. | SATISFIED | External LLM dependence remains a measured limitation. |
| Intuitive user flow | Action-bound forms, clear navigation, stored results, and stable exercises. | Navigation, exactly-once actions, feedback, and failure states passed E2E checks. | SATISFIED | Formal user study was not conducted. |
| Answer questions about model construction | Notebook 04, metadata, features, metrics, and shortcut analysis support explanation. | No oral questioning was observed. | REQUIRES LIVE PRESENTATION | Requires live presentation evidence outside Phase 11. |
| Answer questions about UI construction | Thin router, page modules, cached resources, and rerun-state tests are documented. | No oral questioning was observed. | REQUIRES LIVE PRESENTATION | Requires live presentation evidence outside Phase 11. |
| Notebook IDE for resource/model work | Notebooks 01-05 cover exploration, preprocessing, generation, ML, and evaluation. | Notebook 05 was executed from a fresh kernel against raw result files. | SATISFIED | The saved notebooks use reusable modules instead of duplicating production logic. |
| Source-code organization | Separate UI, services, models, prompts, data, reports, notebooks, and tests. | Complete tests and protected-artifact integrity checks cover module boundaries. | SATISFIED | Evaluation logic is isolated under app/evaluation. |

## 13. Project requirements audit

| ID | Requirement | Implementation evidence | Evaluation evidence | Status | Limitation |
|---|---|---|---|---|---|
| MVP-01 | Streamlit application launches | app.py | real health endpoint and AppTest | SATISFIED | Local MVP only. |
| MVP-02 | User can enter one Finnish sentence | Grammar Checker form | E2E correct and incorrect submissions | SATISFIED | 500-character service limit. |
| MVP-03 | Grammar analysis works | GrammarService and prompt | data/evaluation/grammar_evaluation_results_v1.jsonl | SATISFIED | 39/40 attempts produced validated outputs; one schema failure is retained. |
| MVP-04 | Sentence correction works | typed corrected_sentence | data/evaluation/grammar_evaluation_results_v1.jsonl | PARTIAL | Across 18 erroneous cases, 17 corrections matched exactly and one was incorrect; separately, one valid case had no validated provider output. |
| MVP-05 | Grammar explanation works | per-error and overall explanation fields | data/evaluation/grammar_evaluation_results_v1.jsonl | PARTIAL | AI-assisted review is complete, but four explanations scored 1 for grammatical correctness and four scored 1 for learner usefulness. |
| MVP-06 | Errors are classified | seven-category production taxonomy | data/evaluation/grammar_evaluation_results_v1.jsonl | SATISFIED | Single- and multiple-error metrics use small category supports. |
| MVP-07 | Results are stored | SQLite grammar_checks/grammar_errors | E2E exactly-once and profile scenarios | SATISFIED | Local demo identity; no authentication. |
| MVP-08 | Learner weakness profile updates | ProfileService | controlled temporary-SQLite profile and personalization results | SATISFIED | Confidence is stored but not used as a weight. |
| MVP-09 | Basic vocabulary lookup works | Phase 8 local index and service | data/evaluation/vocabulary_cases_v1.jsonl and final_evaluation_v1.json | SATISFIED | Corpus-bounded, not a complete dictionary. |
| MVP-10 | Basic targeted exercises can be generated | ExerciseService | data/evaluation/exercise_evaluation_results_v1.jsonl | PARTIAL | 20/20 generated and passed structure, but one stored answer/explanation failed linguistic review and distractor quality passed in only 11/20 cases. |
| MVP-11 | ML baseline is trained and loadable | error_classifier_v1.joblib | reloaded pipeline and reproduced predictions | SATISFIED | Three synthetic labels only. |
| MVP-12 | Train/test separation is documented | split manifest and notebook 04 | zero group intersections | SATISFIED | Grouped 70/15/15 approximation. |
| MVP-13 | Evaluation metrics are available | Phase 5 metadata and Phase 11 evaluator | component-specific machine report | SATISFIED | AI-assisted qualitative linguistic review is reported separately from automatic metrics. |
| MVP-14 | Notebooks document data/ML/evaluation | notebooks/01-05 | fresh execution of notebook 05 | SATISFIED | Production logic remains in modules. |
| MVP-15 | Source code is modular | app/ui, services, models, prompts, evaluation | full test suite | SATISFIED | No major feature was added in Phase 11. |
| MVP-16 | API keys are protected | .env.example and ignore rules | no API secret recorded; provider metadata excludes key | SATISFIED | A live key was configured only through the ignored .env file. |
| MVP-17 | Final demo flow works start to finish | six-page UI learning loop | deterministic E2E checks plus live grammar/exercise component outputs | REQUIRES LIVE PRESENTATION | Automated flow checks pass; the assessed live walkthrough remains Phase 12 work. |
| MVP-18 | Limitations are documented | About page and final report | consolidated evidence-based limitations | SATISFIED | Includes synthetic-data and provider limitations. |

## Reproducibility

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m app.evaluation.system_evaluation --project-root . --reuse-live-results --run-tests --include-startup-smoke
$env:PYTHONUTF8 = "1"
$env:IPYTHONDIR = "$PWD\tmp\ipython"
$env:JUPYTER_CONFIG_DIR = "$PWD\tmp\jupyter-config"
$env:JUPYTER_DATA_DIR = "$PWD\tmp\jupyter-data"
$env:JUPYTER_RUNTIME_DIR = "$PWD\tmp\jupyter-runtime"
.\.venv\Scripts\jupyter.exe execute --inplace --timeout=600 notebooks/05_evaluation.ipynb
streamlit run app.py --server.address localhost
```

Embedded complete-suite result: **162 passed, 0 failed, 3 skipped** (`PASS`).

Protected prior-phase files unchanged or covered by an approved Phase 11 bug-fix exception: **True** (24 files checked; byte-for-byte all unchanged: False).

## Verdict

**READY FOR PHASE 12**
