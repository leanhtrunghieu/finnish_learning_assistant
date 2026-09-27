# Demo and Defense Notes

## Presentation truth statement

The preferred demo uses one live grammar request after a single pre-demo availability check. If that check fails, switch immediately to the included fallback screenshots and preserved Phase 11 artifacts. Say: **“This is previously recorded real system output from the frozen Phase 11 evaluation; the provider is unavailable now.”**

Do not describe AI-assisted qualitative linguistic review as human, native-speaker, or Finnish-teacher validation. The Phase 5 classifier uses controlled synthetic learner errors and does not power the production grammar checker.

## Timed eight-minute demo

| Time | View | Presenter action and message |
|---|---|---|
| 0:00–0:45 | Slide 2 | Finnish morphology makes feedback hard: learners need a correction, an understandable rule, and practice connected to repeated mistakes. |
| 0:45–1:15 | Home / Slide 3 | Introduce the implemented loop: write, check, understand, remember, analyze, practice. |
| 1:15–2:30 | Grammar Checker | Enter **Minä menee kouluun.** Submit once. Show **Minä menen kouluun.**, VERB_CONJUGATION, the explanation, and the learning tip. State that output is JSON-extracted and validated as a typed result before rendering or persistence. |
| 2:30–3:15 | My Mistakes | Show that the check appears once, then show error counts, percentages, and the highest supported weakness. Explain that one check and its errors are stored in one SQLite transaction. |
| 3:15–4:00 | Vocabulary | Search **koulu**. Show the lemma, NOUN POS, morphological forms, English sense candidates, and provenance. State that this is a corpus-bounded lexical index, not complete dictionary coverage. |
| 4:00–5:00 | Practice | Generate once from the selected weakness, answer the task, and show feedback. Point out that answer submission keeps the same exercise in session state. |
| 5:00–6:15 | Slide 11 | Give only the headline evidence: detection F1 94.44%; frozen-set false-positive rate 1/22; correction exact match 17/18; structured output 39/40; exercise structure 20/20; answer correctness 19/20 PASS; distractor plausibility 11/20 PASS. State sample sizes and AI-assisted review status. |
| 6:15–7:15 | Slides 4–7 | Explain the actual architecture, traceable data, leakage-group split, and synthetic-data Logistic Regression baseline. The baseline test accuracy is 0.710 and macro F1 is 0.709 on 449 synthetic test examples. |
| 7:15–8:00 | Slide 12 | Close with the two largest boundaries: no authentic learner-error generalization and no Finnish-teacher validation. Name the next evidence needed, not new claims. |

## Key transitions

- **Problem to product:** “A correction is useful once; a stored correction can drive the next learning action.”
- **Grammar to history:** “This validated result is also the unit we persist, so the UI and profile share the same evidence.”
- **History to practice:** “Personalization is deliberately simple and inspectable: the highest supported error count becomes the next target.”
- **Product to evaluation:** “The UI flow works, but structural success is not the same as linguistic quality, so Phase 11 measured them separately.”
- **Evaluation to limitations:** “These figures support an MVP claim, not production-grade Finnish-teacher equivalence.”

## Expected live inputs

- Grammar sentence: `Minä menee kouluun.`
- Expected correction: `Minä menen kouluun.`
- Expected primary category: `VERB_CONJUGATION`
- Vocabulary query: `koulu`
- Demo learner identity: `demo_user`

Use an isolated/disposable demo database or previously prepared local demo state. Never commit the runtime database.

## Rehearsal A — live path

1. Start the app and confirm the health endpoint.
2. Make one pre-demo grammar availability check.
3. If it succeeds, reload the disposable demo state and follow the timed script.
4. Submit each provider action once; do not rerun until a preferred output appears.
5. Keep the presentation open locally in case the network fails after the check.

Phase 12 rehearsal result: the application started and its health endpoint returned `ok`, but the one bounded live grammar request returned the application's safe provider-unavailable message. No retry was made. Therefore, use Rehearsal B unless a single pre-demo availability check succeeds on presentation day.

## Rehearsal B — provider-failure fallback

1. State clearly that the provider is currently unavailable.
2. Use `grammar_result_recorded.png`, `weakness_profile.png`, `vocabulary_koulu.png`, and `practice_recorded.png`.
3. Point to the visible **Previously recorded real system output** label.
4. If detail is requested, open the immutable Phase 11 JSONL records rather than inventing a live response.
5. Continue through evaluation and architecture normally.

The fallback follows the same eight-minute sequence and uses real preserved output. It is evidence of prior system behavior, not evidence of current provider availability.

## Rubric-focused presenter checklist

| Rubric area | Where to demonstrate | Presenter cue |
|---|---|---|
| Real-world problem | Slides 2–3 | Link grammar feedback to repeated learner mistakes and targeted practice. |
| Data transformation | Slides 5–6; notebook 03 | Show correct corpus sentence becoming one controlled synthetic error with provenance. |
| Train/test separation | Slide 7; notebook 04 | Explain `leakage_group_id` and zero group overlap. |
| Evaluation metrics | Slides 7 and 11 | State task, sample size, metric, and limitation together. |
| Prompted LLM functionality | Grammar demo; Slide 8 | Show correction, category, explanation, learning tip, and schema validation. |
| AI-based solution | Slides 7–9 | Distinguish the ML baseline experiment from the production LLM path. |
| Originality | Slides 3 and 9 | Emphasize the feedback-to-profile-to-practice loop. |
| UI quality and intuitive flow | Live pages; Slide 10 | Navigate in the same order as the learning loop. |
| ML construction knowledge | Slides 6–7 | Defend features, model choice, split, metrics, and shortcut risk. |
| UI construction knowledge | Slides 4 and 10 | Explain thin Streamlit pages, service boundaries, explicit actions, and session state. |
| Notebook usage | Slides 5–7 | Point to notebooks 01–05 and reusable modules under `app/`. |
| Source organization | Slide 4; README structure | Identify models, services, UI, evaluation, reports, and versioned artifacts. |
| Presentation/audience performance | Live delivery | Stay within eight minutes, make labels visible, and invite questions. |

## Defense questions and concise answers

### Why synthetic learner errors?

Suitable authentic Finnish learner-error data was not available within scope. Controlled transformations made the baseline reproducible and auditable, but they do not prove real-learner generalization.

### How did you prevent leakage?

Every source sentence and all of its variants share a deterministic `leakage_group_id`. The group-aware split keeps an entire group in one partition; the manifest verifies zero overlap.

### Why Logistic Regression?

It is fast, reproducible, interpretable, and appropriate as a classical educational baseline for sparse character TF-IDF features. It gives a useful comparison without pretending to be the production checker.

### Why use an LLM as well?

The baseline classifies an already-incorrect synthetic sentence into one of three classes. The LLM path must detect correctness in context, identify one or more categories, correct the sentence, and explain the result. They answer different questions.

### How reliable is grammar checking?

On 40 frozen cases, 39 produced validated outputs. Among those predictions, detection F1 was 94.44%; the frozen-set false-positive rate was 1/22; 17/18 applicable corrections matched exactly. This is promising MVP evidence from a small set, not a guarantee for unrestricted Finnish.

### How do you know explanations are correct?

They were scored in an AI-assisted qualitative linguistic review with explicit criteria. Some explanations had substantive issues. A larger review by Finnish teachers is the most important next validation step.

### Why SQLite?

It provides simple transactional local persistence with no deployment overhead and is appropriate for a single-user MVP. Production would need managed identity, access control, migrations, backup, and a managed database.

### How is personalization implemented?

Validated grammar errors are stored by learner. The profile service aggregates exact counts and percentages, applies deterministic ranking and tie behavior, and selects the highest supported category for practice.

### Why Streamlit?

It enabled rapid, testable integration of the Python services. Explicit form submissions and session state also make rerun behavior testable. A production UI could use a dedicated frontend without changing the core service boundaries.

### What is the biggest limitation?

There is limited authentic learner evidence and no real Finnish-teacher evaluation. Those constraints affect both the ML baseline's external validity and confidence in free-form explanations/exercises.

### What would production require?

Authentication, managed persistence, monitoring, provider observability, stronger lexical coverage, robust exercise validation, larger authentic evaluations, Finnish-teacher review, and scalable deployment.

## Presenter final check

- Keep an eight-minute timer visible but off-screen.
- Close all terminals and configuration files before sharing.
- Confirm no API key, local path, or private history is visible.
- Use one live provider attempt only after the availability check.
- If it fails, switch immediately and label the fallback honestly.
- Do not claim that the synthetic baseline powers production.
- Do not claim human/native/Finnish-teacher review.
