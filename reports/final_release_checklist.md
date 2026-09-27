# Final Release Checklist

Evaluation date: **2026-09-13**  
Release candidate: **v1.0.0**  
Release-state result: **PASS — no unresolved release blocker**

## Frozen release-candidate state

- Branch at Phase 12 start: `main`
- HEAD at Phase 12 start: `81646ba03a6123407e39d08e5c68c082d7040ff8`
- Worktree at Phase 12 start: dirty with the approved Phase 11 implementation/evidence; Phase 12 preserved those changes and added only release dependencies, documentation, presentation assets, and this checklist.
- Phase 11 grammar dataset Git object at freeze: `3fbd9c1372ca0073834929a73fcfe6f4be2e41a1`

## Protected Phase 11 evidence

All protected files were SHA-256 checked before and after Phase 12 and remained byte-for-byte unchanged.

| Artifact | Frozen SHA-256 | Status |
|---|---|---|
| `data/evaluation/grammar_cases_v1.jsonl` | `2e336b2842ebc58ca4604e1fb9c6aa99ca01cac36b72e4eb2daec5756424deb5` | PASS |
| `data/evaluation/grammar_evaluation_results_v1.jsonl` | `b33b679ac0112a8dc6647990c4423f7373ef82fdcdd853ae539b9abfda62917c` | PASS |
| `data/evaluation/exercise_evaluation_results_v1.jsonl` | `d62ce7d70b2edc0b042aee2f5ebd50a6eaf539159c29c2c02ffe8982aea14298` | PASS |
| `data/evaluation/grammar_manual_reviews_v1.jsonl` | `35d8878918584dcae45077064a3a6c8f2fcdfed97bce29b2e19b8f329caff3ed` | PASS |
| `data/evaluation/exercise_manual_reviews_v1.jsonl` | `40525c4ee4e591cab8484929f3e4073a83c0d9edc92bab4fde4ee4b4b4b1ef8e` | PASS |
| `reports/final_evaluation.md` | `76d55ee7f0adbf14f13a8ccd39d2e497d6284dba8820c0699ac1d6a85bb1e6e7` | PASS |
| `reports/final_evaluation_v1.json` | `c3b1ff21033b095d9d04324f1405716f6b6d8c7717398d770adf8e15bdb2df8a` | PASS |
| `reports/end_to_end_checklist_v1.md` | `a2550252ac4a94891b3978b71c7a5588734e9603f15c19fa7110f0fadb28489c` | PASS |
| `notebooks/05_evaluation.ipynb` | `653bd699e7be93244388bd08fbe0fb5c60e7ee20bbecc4291e0ddf43b84e4ab8` | PASS |

## Verification checklist

| Area | Status | Evidence / notes |
|---|---|---|
| Git state recorded | PASS | Branch, HEAD, initial dirty status, dataset object, and protected hashes are recorded above. |
| Feature scope frozen | PASS | No application feature, model, prompt, evaluation case, live result, or qualitative rating was changed in Phase 12. |
| Initial full regression | PASS | 162 passed, 3 skipped, 0 failed in the project Python 3.12 environment. |
| Clean-environment regression | PASS | Fresh Python 3.12 venv installed the pinned release requirements; 162 passed, 3 skipped, 0 failed. |
| Final full regression | PASS | 162 passed, 3 skipped, 0 failed after release files were completed. |
| Streamlit startup | PASS | Final `streamlit run app.py` process started without exception. |
| Streamlit health | PASS | `/_stcore/health` returned HTTP 200 and `ok`; the root returned HTTP 200. |
| Navigation | PASS | Six-page navigation remains covered by Streamlit AppTest and the final suite. |
| Provider configuration | PASS | Ignored `.env` loaded; provider/base/model/key fields were present; grammar and exercise use the shared approved transport. Values and secrets were not recorded here. |
| Bounded live grammar smoke | FAIL | Exactly one Phase 12 request for `Minä menee kouluun.` reached the production UI path but returned the application's safe provider-unavailable message. No repeat retry was made. |
| Grammar outage acceptance | PASS | The Phase 12 definition explicitly permits a documented outage; preserved real Phase 11 output and clearly labeled screenshots provide the fallback. |
| Vocabulary known word | PASS | `koulu` returned an ambiguous successful lookup with two analyses, lemma `koulu`, NOUN POS, meanings/forms, and source provenance. |
| Vocabulary unknown word | PASS | `qwertyö` returned the supported not-found behavior without a crash. |
| Disposable demo state | PASS | A separate ignored temporary database was used for `demo_user`; no demo/runtime database was added to the release. |
| Persistence | PASS | Four controlled checks were seeded from preserved evidence; the profile returned four checks and three errors. The failed live provider action inserted nothing. |
| Correct-sentence counts | PASS | The controlled correct sentence remained a check but added no grammar error rows. |
| Profile aggregation | PASS | Controlled state produced CASE_ERROR 2/3 (66.67%) and AGREEMENT 1/3 (33.33%), with CASE_ERROR selected. |
| Practice live generation | NOT APPLICABLE | A second live provider request was deliberately avoided after the bounded grammar smoke documented provider unavailability. Phase 11 retains 20/20 real generation attempts. |
| Practice fallback and checking | PASS | A preserved real Phase 11 exercise was reconstructed through the production model, kept stable, and produced correct deterministic answer feedback. |
| One grammar action = one insertion | PASS | Verified by controlled state and the rerun-safety regression tests. |
| Rendering does not repeat grammar API | PASS | Explicit submit/session-state behavior remains covered by Streamlit integration tests. |
| Answer checking does not regenerate | PASS | Stable exercise identity and no regeneration on answer submission remain covered by tests and the fallback rehearsal. |
| Session state persists on rerun | PASS | Covered by final Streamlit integration tests. |
| README | PASS | Overview, architecture, setup, configuration, run/test/evaluation commands, metrics, limitations, structure, licenses, and handoff links are current. |
| Clean setup instructions | PASS | Dependency installation and tests were executed in a fresh Python 3.12 venv. The current Windows launcher exposed 3.14 only, so creation used the known 3.12 project interpreter; README states the launcher assumption and equivalent. |
| Evaluation notebook command | PASS | A temporary copy of notebook 05 executed from a fresh kernel in the clean environment; the protected notebook was not modified. |
| Presentation structure | PASS | Twelve-slide deck follows the approved problem, loop, architecture, data, ML, product, evidence, and limitations sequence. |
| Presentation metrics | PASS | All reported figures are loaded from or cross-checked against `reports/final_evaluation_v1.json`. |
| Presentation disclosure | PASS | Deck explicitly states synthetic ML data and AI-assisted—not Finnish-teacher—qualitative review. |
| Presentation package validation | PASS | 12 slides, two native editable charts, package integrity pass, font-policy pass, and no layout findings; rendered slides were visually inspected. |
| Architecture diagram | PASS | The deck contains an editable diagram of implemented components; a PNG export is supplied for documentation. |
| Application screenshots | PASS | Five focused screenshots were captured from actual project Streamlit components; preserved-output views visibly label the fallback. |
| Rehearsal A — live | FAIL | Startup succeeded, but the provider was unavailable during the one bounded grammar action. Use this path only if one pre-demo availability check succeeds. |
| Rehearsal B — fallback | PASS | The same approximately eight-minute flow works with labeled screenshots and preserved raw Phase 11 output. |
| `.env` ignored | PASS | `git check-ignore` matched `.env`; only `.env.example` is tracked. |
| Exact configured API key absent | PASS | Zero matches across release text artifacts; the secret value was never printed. |
| Credential-pattern scan | PASS | Zero API-key/Authorization-header patterns found in release text artifacts or presentation XML/notes. |
| Screenshot secret safety | PASS | Focused UI screenshots were visually inspected; no configuration, key, authorization header, or private data is visible. |
| Runtime database excluded | PASS | `database/finnish_learning_assistant.db` remains ignored and is not part of the release. |
| Logs/caches/editor artifacts | PASS | Repository caches and Phase 12 working files were removed; ignored runtime/source environments remain excluded. |
| Large files | PASS | The large committed processed-data and vocabulary-index files are intentional assessment artifacts; no accidental large Phase 12 file was added. |
| Phase 12 scope | PASS | Documentation, presentation, release verification, and reproducibility only; no Phase 13 and no product feature work. |

## Presentation artifact hashes

- `docs/presentation/final_presentation.pptx`: `b7d6cd7afb04969316fdab4a33c121935ba6268fa1b62e1f99881cdfa6f68281`
- `docs/presentation/architecture_diagram.png`: `16ddc0d0b2770d1e66c6efa2fdc95c6d9b2d8345405dacd4e245c6a8b08ff7c0`

## Demo decision

The release is ready for assessment with the **fallback rehearsal as the currently verified demo path**. On presentation day, perform exactly one pre-demo availability check. Use the live path only if it succeeds; otherwise disclose the provider outage and use the labeled real-output fallback.

## Tag gate

All local release checks pass under the documented provider-outage alternative. Create `v1.0.0` only after reviewing and committing the intended Phase 11 and Phase 12 changes.
