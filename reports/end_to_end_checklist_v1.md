# End-to-End Checklist v1

Evaluation date: `2026-09-13T02:23:42Z`

Mutable checks used controlled temporary SQLite databases. PASS is recorded only for executed scenarios.

| Scenario | Result | Evidence |
|---|---|---|
| app_import_and_startup | PASS | Streamlit AppTest loaded app.py without an exception or startup error. |
| all_page_navigation | PASS | Six sidebar routes rendered with isolated database/profile services; failures: none |
| correct_grammar_flow | PASS | One explicit action produced one check row, no error rows, and a rendered correct result. |
| incorrect_multiple_error_flow | PASS | One parent check and two ordered child errors were rendered and persisted. |
| exactly_once_persistence | PASS | Normal result rendering reruns did not repeat grammar analysis or insertion. |
| history_and_profile_update | PASS | Persisted errors were immediately visible as exact profile counts in the isolated database. |
| known_ambiguous_unknown_vocabulary | PASS | Actual local index statuses: {'kouluun': 'found', 'koulu': 'ambiguous', 'qwertyö': 'not_found'}. |
| profile_targeted_practice | PASS | The controlled highest weakness selected a stable VERB_CONJUGATION exercise. |
| deterministic_answer_checking | PASS | Answer checking used the stored exercise and made no generation call. |
| streamlit_rerun_safety | PASS | Grammar render rerun preserved one insert; practice selection/rerun preserved one exercise. |
| missing_api_configuration | PASS | Controlled learner-safe message: The grammar service is not configured. Set LLM_API_KEY, LLM_API_BASE_URL, and LLM_MODEL. |
| provider_failure_handling | PASS | Provider detail was hidden behind: The grammar provider is temporarily unavailable or returned an invalid response. |
| real_streamlit_process_health | PASS | Health response: ok; error: None. |

## Rerun evidence

- One grammar action produced one service call and one database insertion.
- Rendering the stored grammar result did not call the service or insert again.
- Selecting/submitting a practice answer did not generate a replacement exercise.
- Session state retained the same exercise ID through normal reruns.

## Provider limitation

Live provider evidence exists: 39/40 grammar outputs validated and 20/20 exercises generated. AI-assisted qualitative linguistic review remains separate from automatic validation.
