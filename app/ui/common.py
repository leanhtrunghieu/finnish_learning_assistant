"""Shared presentation helpers and Streamlit session-state conventions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import streamlit as st

from app.models.grammar import ErrorType


DEFAULT_LEARNER_ID = "demo_user"

ERROR_TYPE_LABELS: Mapping[ErrorType, str] = {
    ErrorType.CASE_ERROR: "Case error",
    ErrorType.VERB_CONJUGATION: "Verb conjugation",
    ErrorType.NOUN_INFLECTION: "Noun inflection",
    ErrorType.WORD_ORDER: "Word order",
    ErrorType.AGREEMENT: "Agreement",
    ErrorType.SPELLING: "Spelling",
    ErrorType.OTHER: "Other",
}


def error_type_label(error_type: ErrorType | str) -> str:
    """Map a canonical error identifier to a learner-friendly label."""

    if isinstance(error_type, ErrorType):
        return ERROR_TYPE_LABELS[error_type]
    try:
        return ERROR_TYPE_LABELS[ErrorType(error_type)]
    except (TypeError, ValueError):
        return str(error_type).replace("_", " ").title()


def initialize_session_state() -> None:
    """Initialize only UI state; business data remains in the services."""

    defaults: dict[str, Any] = {
        "nav_page": "Home",
        "grammar_result": None,
        "grammar_check_id": None,
        "grammar_save_error": None,
        "vocabulary_result": None,
        "practice_exercise": None,
        "practice_attempt": None,
        "practice_generation_error": None,
        "practice_requested_topic": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def navigate_to(page: str) -> None:
    """Move to an existing application page from an in-page action."""

    st.session_state["nav_page"] = page


def navigate_to_practice(error_type: ErrorType) -> None:
    """Open Practice with an existing supported error type selected."""

    clear_practice_state()
    st.session_state["practice_requested_topic"] = error_type
    st.session_state["nav_page"] = "Practice"


def format_activity_time(value: str) -> str:
    """Format stored timestamps without guessing a timezone for naive values."""

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return value
    formatted = timestamp.strftime("%d %b %Y, %H:%M")
    if timestamp.tzinfo is None:
        return formatted
    zone = timestamp.tzname() or timestamp.strftime("UTC%z")
    return f"{formatted} {zone}"


def profile_rows(profile: Any) -> list[dict[str, Any]]:
    """Convert a typed learner profile to compact table rows."""

    return [
        {
            "Error type": error_type_label(weakness.error_type),
            "Count": weakness.count,
            "Percentage": f"{weakness.percentage:.0f}%",
        }
        for weakness in profile.weaknesses
    ]


def clear_practice_state() -> None:
    """Forget the current exercise and answer after an explicit new request."""

    st.session_state["practice_exercise"] = None
    st.session_state["practice_attempt"] = None
    st.session_state["practice_generation_error"] = None
