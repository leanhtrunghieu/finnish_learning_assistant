"""Streamlit vocabulary lookup page."""

from __future__ import annotations

import streamlit as st

from app.models.vocabulary import VocabularyResult, VocabularyStatus
from app.services.vocabulary_service import VocabularyInputError, VocabularyService
from app.ui.services import get_vocabulary_service


def _render_analysis(analysis: object, index: int) -> None:
    """Render one source-backed lexical analysis."""

    st.markdown(f"### Analysis {index}")
    st.write(f"**Lemma:** {analysis.lemma}")
    st.write(f"**Part of speech:** {analysis.part_of_speech}")
    if analysis.meanings:
        st.write("**English meanings:** " + ", ".join(analysis.meanings))
    else:
        st.caption("No verified English meaning is available for this analysis.")
    if analysis.observed_forms:
        st.write("**Observed forms:**")
        st.dataframe(
            [
                {
                    "Form": form.form,
                    "Count": form.count,
                    "Features": ", ".join(f"{key}={value}" for key, value in form.features.items())
                    or "—",
                }
                for form in analysis.observed_forms[:20]
            ],
            hide_index=True,
            width="stretch",
        )
    if analysis.example:
        st.write(f"**Corpus example:** {analysis.example.sentence}")
        st.caption(f"Example source: {analysis.example.source_dataset} / {analysis.example.source_id}")
    if analysis.usage_note:
        st.info(analysis.usage_note)
    if analysis.sources:
        st.caption(
            "Sources: "
            + "; ".join(
                f"{source.name} ({source.license})"
                for source in analysis.sources
            )
        )


def render_vocabulary_page(*, vocabulary_service: VocabularyService | None = None) -> None:
    """Render explicit local lookup and its found/ambiguous/not-found states."""

    st.title("Vocabulary")
    st.write("Look up a Finnish word or observed inflected form in the local lexical index.")
    with st.form("vocabulary_form", clear_on_submit=False):
        query = st.text_input("Finnish word", key="vocabulary_query", placeholder="koulu")
        submitted = st.form_submit_button("Look up word", type="primary")

    if submitted:
        st.session_state["vocabulary_result"] = None
        if not query.strip():
            st.warning("Enter a Finnish word first.")
        else:
            try:
                service = vocabulary_service or get_vocabulary_service()
                with st.spinner("Looking up the word…"):
                    st.session_state["vocabulary_result"] = service.lookup(query)
            except VocabularyInputError as exc:
                st.warning(str(exc))
            except (OSError, ValueError):
                st.error("The local vocabulary index could not be loaded.")
            except Exception:
                st.error("Vocabulary lookup is temporarily unavailable.")

    result = st.session_state.get("vocabulary_result")
    if not isinstance(result, VocabularyResult):
        return
    if result.status is VocabularyStatus.NOT_FOUND:
        st.info(f"No verified vocabulary result was found for `{result.query}`.")
        return
    if result.status is VocabularyStatus.AMBIGUOUS:
        st.warning("This form has multiple corpus-supported analyses. Review them rather than assuming one meaning.")
    else:
        st.success(f"Found a vocabulary result for `{result.query}`.")
    for index, analysis in enumerate(result.analyses, start=1):
        _render_analysis(analysis, index)
    for warning in result.warnings:
        st.caption(f"Note: {warning}")
