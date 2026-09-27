"""Thin Streamlit router for the Finnish Learning Assistant MVP."""

import logging

import streamlit as st

from app.config import get_settings
from app.ui.about_page import render_about_page
from app.ui.common import initialize_session_state
from app.ui.grammar_page import render_grammar_page
from app.ui.history_page import render_history_page
from app.ui.home import render_home
from app.ui.practice_page import render_practice_page
from app.ui.theme import apply_global_styles
from app.ui.vocabulary_page import render_vocabulary_page
from app.utils.errors import ApplicationError
from app.utils.logging_config import configure_logging


LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Start the integrated Streamlit application with safe startup handling."""

    try:
        settings = get_settings()
        configure_logging(settings.log_level)
        st.set_page_config(
            page_title=settings.app_title,
            page_icon="🇫🇮",
            layout="wide",
            initial_sidebar_state="expanded",
        )
        initialize_session_state()
        apply_global_styles()
        LOGGER.info(
            "Starting %s in %s environment.",
            settings.app_title,
            settings.environment,
        )
        st.sidebar.html(
            '<div class="fla-brand">'
            '<span class="fla-brand-mark" aria-hidden="true">FI</span>'
            '<span class="fla-brand-name">Finnish Learning<br>Assistant</span>'
            "</div>"
        )
        st.sidebar.caption("A calm space for focused Finnish practice.")
        st.sidebar.markdown("#### Learn")
        page = st.sidebar.radio(
            "Navigate",
            options=("Home", "Grammar Checker", "Vocabulary", "My Mistakes", "Practice", "About"),
            key="nav_page",
        )
        st.sidebar.divider()
        st.sidebar.caption("Check · understand · remember · practice")
        if page != "Practice":
            st.session_state["practice_requested_topic"] = None
        if page == "Home":
            render_home(settings)
        elif page == "Grammar Checker":
            render_grammar_page(settings=settings)
        elif page == "Vocabulary":
            render_vocabulary_page()
        elif page == "My Mistakes":
            render_history_page()
        elif page == "Practice":
            render_practice_page()
        elif page == "About":
            render_about_page()
    except ApplicationError as exc:
        LOGGER.error("Application startup failed: %s", exc)
        st.error("The application could not start because its configuration is invalid.")
    except Exception:
        LOGGER.exception("Unexpected application startup failure.")
        st.error("The application could not start. Check the application logs for details.")


if __name__ == "__main__":
    main()
