"""Learner history and weakness-profile page."""

from __future__ import annotations

import streamlit as st

from app.services.database_service import DatabaseError, DatabaseService, DEFAULT_LEARNER_ID
from app.services.profile_service import ProfileService
from app.ui.common import error_type_label, format_activity_time, navigate_to
from app.ui.services import get_database_service, get_profile_service
from app.ui.theme import render_empty_state, render_eyebrow, render_status_badge


def render_history_page(
    *,
    learner_id: str = DEFAULT_LEARNER_ID,
    database_service: DatabaseService | None = None,
    profile_service: ProfileService | None = None,
) -> None:
    """Render fresh learner history/profile data without caching user state."""

    render_eyebrow("Turn mistakes into progress")
    st.title("My Mistakes")
    st.write("Review recent feedback, notice recurring patterns, and choose what to practise next.")
    try:
        database = database_service or get_database_service()
        profile = (profile_service or get_profile_service()).get_profile(learner_id)
        checks = database.get_recent_checks(learner_id, limit=20)
    except DatabaseError:
        st.error("Learner history is temporarily unavailable.")
        return
    except Exception:
        st.error("Learner history could not be loaded.")
        return

    metrics = st.columns(3)
    metrics[0].metric(
        "Sentences checked",
        profile.total_checks,
        border=True,
        icon=":material/spellcheck:",
    )
    metrics[1].metric(
        "Mistakes reviewed",
        profile.total_errors,
        border=True,
        icon=":material/rule:",
    )
    metrics[2].metric(
        "Current focus",
        error_type_label(profile.primary_weakness) if profile.primary_weakness else "None yet",
        border=True,
        icon=":material/target:",
    )

    st.subheader("Focus areas")
    if profile.weaknesses:
        for weakness in profile.weaknesses:
            mistake_word = "mistake" if weakness.count == 1 else "mistakes"
            with st.container(border=True):
                heading, count = st.columns([3, 1])
                heading.markdown(f"**{error_type_label(weakness.error_type)}**")
                count.markdown(f"**{weakness.count}** {mistake_word}")
                st.progress(
                    min(max(weakness.percentage / 100, 0.0), 1.0),
                    text=(
                        f"{weakness.count} of {profile.total_errors} mistakes "
                        f"({weakness.percentage:.0f}%)"
                    ),
                )
        st.button(
            "Practise your current focus",
            key="history_open_practice",
            type="primary",
            icon=":material/fitness_center:",
            on_click=navigate_to,
            args=("Practice",),
        )
    else:
        render_empty_state(
            "No recurring mistakes yet",
            "Check a few Finnish sentences to build your learning profile.",
        )

    st.subheader("Recent checks")
    if not checks:
        render_empty_state(
            "No sentence checks yet",
            "Your corrected sentences and explanations will appear here.",
        )
        st.button(
            "Check a sentence",
            key="history_open_grammar",
            type="primary",
            icon=":material/edit_note:",
            on_click=navigate_to,
            args=("Grammar Checker",),
        )
        return

    error_filters = sorted(
        {
            error_type_label(error.error_type)
            for check in checks
            for error in check.errors
        }
    )
    selected_filter = st.selectbox(
        "Filter recent checks",
        options=["All checks", "Correct", *error_filters],
        key="history_filter",
    )
    if selected_filter == "Correct":
        visible_checks = [check for check in checks if check.is_correct]
    elif selected_filter == "All checks":
        visible_checks = list(checks)
    else:
        visible_checks = [
            check
            for check in checks
            if any(error_type_label(error.error_type) == selected_filter for error in check.errors)
        ]

    if not visible_checks:
        render_empty_state(
            "No checks match this filter",
            "Choose another focus area to see more of your history.",
        )
        return

    for check in visible_checks:
        error_count = len(check.errors)
        mistake_word = "mistake" if error_count == 1 else "mistakes"
        status = "Correct" if check.is_correct else f"Needs review · {error_count} {mistake_word}"
        marker = "✓" if check.is_correct else "!"
        label = f"{marker} {status} · {format_activity_time(check.created_at)} — {check.original_sentence}"
        with st.expander(label):
            render_status_badge(
                status,
                tone="success" if check.is_correct else "warning",
            )
            if not check.is_correct:
                st.markdown(f"**Corrected sentence:** {check.corrected_sentence}")
            if check.errors:
                for error in check.errors:
                    with st.container(border=True):
                        st.markdown(f"**{error_type_label(error.error_type)}**")
                        st.markdown(f"`{error.error_text}`  →  **{error.correction}**")
                        st.write(error.explanation)
            else:
                st.write("No grammar mistakes were found in this sentence.")
            if check.overall_explanation:
                st.caption(check.overall_explanation)
            if check.learning_tip:
                st.info(check.learning_tip, icon="💡")
