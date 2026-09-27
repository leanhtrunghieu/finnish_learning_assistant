"""Streamlit grammar-checker page with explicit, rerun-safe actions."""

from __future__ import annotations

import streamlit as st

from app.config import Settings
from app.models.exercise import SUPPORTED_GENERATION_ERROR_TYPES
from app.models.grammar import MAX_SENTENCE_CHARS, GrammarResult, LanguageMode
from app.services.database_service import DatabaseError, DatabaseService, DEFAULT_LEARNER_ID
from app.services.grammar_service import GrammarService, GrammarServiceError
from app.ui.common import error_type_label, navigate_to, navigate_to_practice
from app.ui.services import get_database_service, get_grammar_service
from app.ui.theme import render_eyebrow


def _language_mode_label(mode: LanguageMode) -> str:
    return {
        LanguageMode.STANDARD: "Standard written Finnish",
        LanguageMode.COLLOQUIAL_TOLERANT: "Colloquial-tolerant Finnish",
    }[mode]


def render_grammar_result(result: GrammarResult, *, check_id: int | None = None) -> None:
    """Render a validated result without exposing provider JSON."""

    st.subheader("Your feedback")
    if result.is_correct:
        st.success("No grammar errors detected", icon="✅")
        with st.container(border=True):
            st.caption("YOUR SENTENCE")
            st.markdown(f"### {result.original_sentence}")
    else:
        st.error(
            f"Review {len(result.errors)} grammar mistake(s)",
            icon="❌",
        )
        comparison = st.columns(2)
        with comparison[0]:
            with st.container(border=True):
                st.caption("YOUR SENTENCE")
                st.markdown(f"### {result.original_sentence}")
        with comparison[1]:
            with st.container(border=True):
                st.caption("CORRECTED SENTENCE")
                st.markdown(f"### {result.corrected_sentence}")

        st.markdown("#### What changed")
        for index, error in enumerate(result.errors, start=1):
            with st.container(border=True):
                st.markdown(f"**{index}. {error_type_label(error.error_type)}**")
                st.markdown(f"`{error.text}`  →  **{error.correction}**")
                st.write(error.explanation)
                if error.error_type in SUPPORTED_GENERATION_ERROR_TYPES:
                    st.button(
                        "Practice this pattern",
                        key=f"practice_error_{index}_{error.error_type.value}",
                        type="tertiary",
                        icon=":material/fitness_center:",
                        on_click=navigate_to_practice,
                        args=(error.error_type,),
                    )
    if result.analysis_status.value == "UNCERTAIN" and result.uncertainty_note:
        st.warning(f"This analysis may need a closer look: {result.uncertainty_note}")
    if result.overall_explanation:
        with st.container(border=True):
            st.markdown("#### Why this works")
            st.write(result.overall_explanation)
    if result.learning_tip:
        st.info(f"**Learning tip**  \n{result.learning_tip}", icon="💡")
    if result.errors:
        with st.expander("Technical details", icon=":material/info:"):
            st.caption(
                "These provider-reported confidence values are technical metadata, not a guarantee of correctness."
            )
            for index, error in enumerate(result.errors, start=1):
                st.write(
                    f"Error {index} · {error_type_label(error.error_type)} · "
                    f"confidence {error.confidence:.2f}"
                )
    if check_id is not None:
        st.caption("Saved to your learning history.")

    st.button(
        "View in My Mistakes",
        key=f"view_history_{check_id or 'current'}",
        icon=":material/history:",
        on_click=navigate_to,
        args=("My Mistakes",),
    )


def analyze_and_persist(
    sentence: str,
    *,
    language_mode: LanguageMode,
    learner_id: str,
    grammar_service: GrammarService,
    database_service: DatabaseService,
) -> tuple[GrammarResult, int | None, str | None]:
    """Run one explicit analysis and one explicit persistence operation.

    Keeping this action boundary in a small function makes the rerun-sensitive
    behavior easy to test: the UI calls it only from the submitted form branch.
    """

    result = grammar_service.check_sentence(sentence, language_mode=language_mode)
    try:
        check_id = database_service.save_grammar_result(learner_id, result)
    except DatabaseError:
        return result, None, "The analysis succeeded, but it could not be saved to learner history."
    except Exception:
        return result, None, "The analysis succeeded, but learner history is temporarily unavailable."
    return result, check_id, None


def render_grammar_page(
    *,
    settings: Settings,
    learner_id: str = DEFAULT_LEARNER_ID,
    grammar_service: GrammarService | None = None,
    database_service: DatabaseService | None = None,
) -> None:
    """Render grammar analysis; provider calls happen only on form submit."""

    render_eyebrow("Check and understand")
    st.title("Grammar Checker")
    st.write("Write one Finnish sentence. You will get a clear correction and an explanation you can learn from.")
    with st.form("grammar_form", clear_on_submit=False):
        sentence = st.text_area(
            "Finnish sentence",
            key="grammar_sentence_input",
            height=120,
            max_chars=MAX_SENTENCE_CHARS,
            placeholder="Minä menee kouluun.",
            help=f"Enter one sentence, up to {MAX_SENTENCE_CHARS} characters.",
        )
        with st.expander("Analysis preferences", icon=":material/tune:"):
            st.caption(
                "Standard checks formal written Finnish. Colloquial-tolerant accepts common spoken structures when appropriate."
            )
            mode = st.selectbox(
                "Finnish style",
                options=list(LanguageMode),
                format_func=_language_mode_label,
                key="grammar_language_mode",
                help="Choose the style you want the sentence to be checked against.",
            )
        submitted = st.form_submit_button(
            "Check my sentence",
            type="primary",
            icon=":material/spellcheck:",
            width="stretch",
        )

    if submitted:
        st.session_state["grammar_result"] = None
        st.session_state["grammar_check_id"] = None
        st.session_state["grammar_save_error"] = None
        if not sentence.strip():
            st.warning("Enter a Finnish sentence first.")
        else:
            try:
                service = grammar_service or get_grammar_service()
                database = database_service or get_database_service()
                with st.spinner("Analyzing Finnish grammar…"):
                    result, check_id, save_error = analyze_and_persist(
                        sentence,
                        language_mode=mode,
                        learner_id=learner_id,
                        grammar_service=service,
                        database_service=database,
                    )
            except GrammarServiceError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Grammar analysis is temporarily unavailable. Please try again later.")
            else:
                st.session_state["grammar_result"] = result
                st.session_state["grammar_check_id"] = check_id
                st.session_state["grammar_save_error"] = save_error

    if st.session_state.get("grammar_save_error"):
        st.warning(st.session_state["grammar_save_error"])
    result = st.session_state.get("grammar_result")
    if isinstance(result, GrammarResult):
        render_grammar_result(result, check_id=st.session_state.get("grammar_check_id"))
