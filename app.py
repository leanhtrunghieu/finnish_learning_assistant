"""Streamlit entry point for the Finnish Learning Assistant."""

import logging

import streamlit as st

from app.config import get_settings
from app.ui.home import render_home
from app.utils.errors import ApplicationError
from app.utils.logging_config import configure_logging


LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Start the Phase 1 Streamlit shell with safe startup handling."""

    try:
        settings = get_settings()
        configure_logging(settings.log_level)
        st.set_page_config(
            page_title=settings.app_title,
            page_icon="🇫🇮",
            layout="centered",
        )
        LOGGER.info(
            "Starting %s in %s environment.",
            settings.app_title,
            settings.environment,
        )
        render_home(settings)
    except ApplicationError as exc:
        LOGGER.error("Application startup failed: %s", exc)
        st.error("The application could not start because its configuration is invalid.")
    except Exception:
        LOGGER.exception("Unexpected application startup failure.")
        st.error("The application could not start. Check the application logs for details.")


if __name__ == "__main__":
    main()
