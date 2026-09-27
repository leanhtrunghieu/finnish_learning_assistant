"""About page for the Finnish Learning Assistant demo."""

from __future__ import annotations

import streamlit as st

from app.ui.theme import render_eyebrow


def render_about_page() -> None:
    """Render concise architecture, provenance, and limitation notes."""

    render_eyebrow("About the learning experience")
    st.title("About")
    st.write(
        "Finnish Learning Assistant helps you check Finnish grammar, understand recurring "
        "mistakes, explore words, and practise focused grammar topics."
    )
    st.subheader("How learning works")
    steps = st.columns(4)
    for column, title, description in zip(
        steps,
        ("Check", "Understand", "Remember", "Practice"),
        (
            "Write one Finnish sentence.",
            "Review the correction and explanation.",
            "Notice patterns in your learning history.",
            "Strengthen the area that needs attention.",
        ),
        strict=True,
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.write(description)

    st.subheader("Privacy and limitations")
    st.write(
        "Learning history is stored in the application's local database. This version does "
        "not include user accounts, and its grammar and vocabulary guidance should be used "
        "as learning support rather than as a complete language authority."
    )

    with st.expander("Technical details", icon=":material/info:"):
        st.markdown("**How the application is built**")
        st.write(
            "Streamlit provides the interface. Grammar analysis and exercise generation use "
            "the configured language-model service, learning history is stored in SQLite, and "
            "vocabulary information comes from documented FinnWordNet and UD-derived data."
        )
        st.markdown("**AI and data disclosure**")
        st.write(
            "The experimental Logistic Regression model does not override grammar feedback. "
            "Generated content is not a dictionary authority, and provider-reported confidence "
            "is not a calibrated probability."
        )
