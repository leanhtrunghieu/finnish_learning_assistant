"""Streamlit vocabulary lookup page."""

from __future__ import annotations

import streamlit as st

from app.models.vocabulary import VocabularyAnalysis, VocabularyResult, VocabularyStatus
from app.services.vocabulary_service import VocabularyInputError, VocabularyService
from app.ui.services import get_vocabulary_service
from app.ui.theme import render_chips, render_empty_state, render_eyebrow


_CASE_LABELS = {
    "Nom": "Nominative",
    "Gen": "Genitive",
    "Acc": "Accusative",
    "Par": "Partitive",
    "Ine": "Inessive",
    "Ela": "Elative",
    "Ill": "Illative",
    "Ade": "Adessive",
    "Abl": "Ablative",
    "All": "Allative",
    "Ess": "Essive",
    "Tra": "Translative",
    "Ins": "Instructive",
    "Abe": "Abessive",
    "Com": "Comitative",
}
_NUMBER_LABELS = {"Sing": "Singular", "Plur": "Plural"}
_FEATURE_LABELS = {
    "Person": "Person",
    "Tense": "Tense",
    "Mood": "Mood",
    "Voice": "Voice",
    "VerbForm": "Verb form",
    "Degree": "Degree",
    "Polarity": "Polarity",
    "Poss": "Possessive",
}
_PART_OF_SPEECH_LABELS = {
    "ADJ": "Adjective",
    "ADP": "Adposition",
    "ADV": "Adverb",
    "AUX": "Auxiliary verb",
    "CCONJ": "Coordinating conjunction",
    "DET": "Determiner",
    "INTJ": "Interjection",
    "NOUN": "Noun",
    "NUM": "Numeral",
    "PART": "Particle",
    "PRON": "Pronoun",
    "PROPN": "Proper noun",
    "SCONJ": "Subordinating conjunction",
    "VERB": "Verb",
}


def _format_features(features: dict[str, str]) -> str:
    """Turn compact morphology codes into readable presentation text."""

    parts: list[str] = []
    case = _CASE_LABELS.get(features.get("Case", ""), features.get("Case"))
    number = _NUMBER_LABELS.get(features.get("Number", ""), features.get("Number"))
    if case and number:
        parts.append(f"{case} {number.lower()}")
    elif case:
        parts.append(case)
    elif number:
        parts.append(number)
    for key, value in features.items():
        if key in {"Case", "Number"}:
            continue
        parts.append(f"{_FEATURE_LABELS.get(key, key)}: {value}")
    return ", ".join(parts) or "No additional grammar details"


def _format_part_of_speech(value: str) -> str:
    return _PART_OF_SPEECH_LABELS.get(value.upper(), value.replace("_", " ").title())


def _render_analysis(analysis: VocabularyAnalysis, index: int) -> None:
    """Render one source-backed lexical analysis."""

    with st.container(border=True):
        st.caption(f"ANALYSIS {index}")
        identity = st.columns(2)
        identity[0].markdown(f"### {analysis.lemma}")
        identity[0].caption("DICTIONARY FORM")
        identity[1].markdown(f"### {_format_part_of_speech(analysis.part_of_speech)}")
        identity[1].caption("PART OF SPEECH")

        st.markdown("**English meanings**")
        if analysis.meanings:
            render_chips(analysis.meanings[:3])
            if len(analysis.meanings) > 3:
                with st.expander(f"Show {len(analysis.meanings) - 3} more meaning(s)"):
                    render_chips(analysis.meanings[3:])
        else:
            st.caption("No verified English meaning is available for this analysis.")

        if analysis.example:
            st.markdown("**Example in context**")
            st.write(analysis.example.sentence)
        if analysis.usage_note:
            st.info(analysis.usage_note, icon="💡")

        if analysis.observed_forms:
            with st.expander(
                f"Forms and grammar details ({len(analysis.observed_forms[:20])})",
                icon=":material/format_list_bulleted:",
            ):
                st.dataframe(
                    [
                        {
                            "Form": form.form,
                            "Occurrences": form.count,
                            "Grammar": _format_features(form.features),
                        }
                        for form in analysis.observed_forms[:20]
                    ],
                    hide_index=True,
                    width="stretch",
                )

        if analysis.example or analysis.sources:
            with st.expander("Sources and attribution", icon=":material/source:"):
                if analysis.example:
                    st.caption(
                        f"Example: {analysis.example.source_dataset} / {analysis.example.source_id}"
                    )
                if analysis.sources:
                    st.caption(
                        "; ".join(
                            f"{source.name} ({source.license})"
                            for source in analysis.sources
                        )
                    )


def render_vocabulary_page(*, vocabulary_service: VocabularyService | None = None) -> None:
    """Render explicit local lookup and its found/ambiguous/not-found states."""

    render_eyebrow("Words in context")
    st.title("Vocabulary")
    st.write("Search for a Finnish word or inflected form and explore how it is used.")
    with st.form("vocabulary_form", clear_on_submit=False):
        query = st.text_input(
            "Finnish word",
            key="vocabulary_query",
            placeholder="Try koulu",
            help="Enter one Finnish word or an inflected form.",
        )
        submitted = st.form_submit_button(
            "Search vocabulary",
            type="primary",
            icon=":material/search:",
            width="stretch",
        )

    if submitted:
        st.session_state["vocabulary_result"] = None
        if not query.strip():
            st.warning("Enter a Finnish word before searching.")
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
        render_empty_state(
            "Ready to explore a word",
            "Search for a word such as koulu, talossa, or menen.",
        )
        return
    if result.status is VocabularyStatus.NOT_FOUND:
        render_empty_state(
            f"No result for “{result.query}”",
            "Check the spelling or try the word in its dictionary form.",
        )
        return
    if result.status is VocabularyStatus.AMBIGUOUS:
        st.warning(
            "This form can be understood in more than one way. Compare the analyses below.",
            icon="⚖️",
        )
    else:
        st.success(f"Vocabulary result for **{result.query}**", icon="✅")
    for index, analysis in enumerate(result.analyses, start=1):
        _render_analysis(analysis, index)
    if result.warnings:
        with st.expander("Data notes", icon=":material/info:"):
            for warning in result.warnings:
                st.caption(warning)
