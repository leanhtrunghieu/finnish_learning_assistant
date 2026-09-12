"""Streamlit grammar-checker page with explicit, rerun-safe actions."""

from __future__ import annotations

import streamlit as st

from app.config import Settings
from app.models.grammar import GrammarResult, LanguageMode
from app.services.database_service import DatabaseError, DatabaseService, DEFAULT_LEARNER_ID
from app.services.grammar_service import GrammarService, GrammarServiceError
from app.ui.common import error_type_label
from app.ui.services import get_database_service, get_grammar_service


def _language_mode_label(mode: LanguageMode) -> str:
    return {
        LanguageMode.STANDARD: "Standard written Finnish",
        LanguageMode.COLLOQUIAL_TOLERANT: "Colloquial-tolerant Finnish",
    }[mode]


def render_grammar_result(result: GrammarResult, *, check_id: int | None = None) -> None:
    """Render a validated result without exposing provider JSON."""

    st.subheader("Result")
    st.caption(f"Original: {result.original_sentence}")
    if result.is_correct:
        st.success("✓ No grammar errors detected")
    else:
        st.error("Grammar issue detected")
        st.markdown(f"**Corrected sentence:** {result.corrected_sentence}")
        st.markdown("**Detected errors**")
        for index, error in enumerate(result.errors, start=1):
            with st.container(border=True):
                st.markdown(f"**{index}. {error_type_label(error.error_type)}**")
                st.write(f"Text: `{error.text}` → `{error.correction}`")
                st.write(error.explanation)
                st.caption(f"Model-reported confidence: {error.confidence:.2f}")
    if result.analysis_status.value == "UNCERTAIN" and result.uncertainty_note:
        st.warning(f"Analysis uncertainty: {result.uncertainty_note}")
    if result.overall_explanation:
        st.markdown(f"**Explanation:** {result.overall_explanation}")
    if result.learning_tip:
        st.info(f"**Learning tip:** {result.learning_tip}")
    if check_id is not None:
        st.caption(f"Saved to learner history (check {check_id}).")


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

    st.title("Grammar Checker")
    st.write("Enter one Finnish sentence and receive a structured, learner-friendly analysis.")
    with st.form("grammar_form", clear_on_submit=False):
        sentence = st.text_area(
            "Finnish sentence",
            key="grammar_sentence_input",
            height=120,
            placeholder="Minä menee kouluun.",
        )
        mode = st.selectbox(
            "Analysis mode",
            options=list(LanguageMode),
            format_func=_language_mode_label,
            key="grammar_language_mode",
        )
        submitted = st.form_submit_button("Check Grammar", type="primary")

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
