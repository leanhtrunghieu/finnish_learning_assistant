"""Initial Streamlit home screen for Phase 1."""

import streamlit as st

from app.config import Settings


APP_DESCRIPTION = (
    "An AI-powered learning assistant that will help Finnish learners "
    "understand grammar, track recurring mistakes, and practise targeted skills."
)


def render_home(settings: Settings) -> None:
    """Render the Phase 1 application shell."""

    st.title(settings.app_title)
    st.write(APP_DESCRIPTION)
    st.divider()
    st.subheader("Project foundation")
    st.write(
        "The Streamlit shell, configuration, logging, and test structure are "
        "ready for the later data and learning phases."
    )
    st.info(
        "Grammar analysis and learner features will be added in later phases."
    )

