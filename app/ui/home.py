"""Home screen for the Finnish Learning Assistant."""

import streamlit as st

from app.config import Settings


APP_DESCRIPTION = (
    "An AI-powered learning assistant that will help Finnish learners "
    "understand grammar, track recurring mistakes, and practise targeted skills."
)


def render_home(settings: Settings) -> None:
    """Render a concise landing page for the integrated MVP."""

    st.title(settings.app_title)
    st.write(APP_DESCRIPTION)
    st.divider()
    st.subheader("Your learning loop")
    st.markdown("**Write → Check → Understand → Remember → Analyze → Practice**")
    st.write(
        "Check a Finnish sentence, review the explanation, see recurring weaknesses, "
        "look up a word, and practise a targeted grammar topic. Use the navigation in "
        "the sidebar to begin."
    )
    left, middle, right = st.columns(3)
    with left:
        st.info("**Grammar Checker**\n\nFind errors and understand the correction.")
    with middle:
        st.info("**Vocabulary**\n\nExplore corpus-backed Finnish forms and meanings.")
    with right:
        st.info("**Practice**\n\nWork on the grammar weakness that appears most often.")

