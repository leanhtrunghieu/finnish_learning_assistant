"""Home screen for the Finnish Learning Assistant."""

import streamlit as st

from app.config import Settings
from app.services.database_service import DatabaseError, DatabaseService, DEFAULT_LEARNER_ID
from app.services.profile_service import ProfileService
from app.ui.common import error_type_label, format_activity_time, navigate_to
from app.ui.services import get_database_service, get_profile_service
from app.ui.theme import render_empty_state, render_eyebrow, render_status_badge


APP_DESCRIPTION = (
    "A calm learning space that helps Finnish learners build stronger grammar skills "
    "one sentence at a time through clear feedback and focused practice."
)


def render_home(
    settings: Settings,
    *,
    learner_id: str = DEFAULT_LEARNER_ID,
    profile_service: ProfileService | None = None,
    database_service: DatabaseService | None = None,
) -> None:
    """Render the learner dashboard from existing profile and history data."""

    render_eyebrow("Your Finnish learning space")
    st.title(settings.app_title)
    st.write(APP_DESCRIPTION)

    profile = None
    recent_checks = ()
    try:
        profile = (profile_service or get_profile_service()).get_profile(learner_id)
        recent_checks = (database_service or get_database_service()).get_recent_checks(
            learner_id,
            limit=1,
        )
    except DatabaseError:
        st.warning("Your learning overview is unavailable right now. You can still use every learning tool.")
    except Exception:
        st.warning("Your learning overview could not be loaded. You can still continue learning.")

    action_left, action_right = st.columns([1.4, 1])
    primary_label = "Check your first sentence" if not profile or profile.total_checks == 0 else "Check another sentence"
    with action_left:
        st.button(
            primary_label,
            key="home_check_sentence",
            type="primary",
            icon=":material/edit_note:",
            width="stretch",
            on_click=navigate_to,
            args=("Grammar Checker",),
        )
    with action_right:
        continue_page = "Practice" if profile and profile.total_errors else "Vocabulary"
        continue_label = "Continue with practice" if continue_page == "Practice" else "Explore vocabulary"
        st.button(
            continue_label,
            key="home_continue",
            icon=":material/arrow_forward:",
            width="stretch",
            on_click=navigate_to,
            args=(continue_page,),
        )

    if profile is not None:
        st.subheader("Your learning overview")
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
            error_type_label(profile.primary_weakness) if profile.primary_weakness else "Build your profile",
            border=True,
            icon=":material/target:",
        )

    st.subheader("Check → Review → Save → Practice")
    steps = (
        ("01", "Check", "Write one Finnish sentence."),
        ("02", "Review", "Understand each correction."),
        ("03", "Save", "Build a picture of recurring mistakes."),
        ("04", "Practice", "Strengthen the pattern that needs attention."),
    )
    for column, (number, title, description) in zip(st.columns(4), steps, strict=True):
        with column:
            with st.container(border=True):
                st.caption(f"STEP {number}")
                st.markdown(f"**{title}**")
                st.write(description)

    st.subheader("Learning tools")
    left, middle_left, middle_right, right = st.columns(4)
    with left:
        st.button(
            "Grammar Checker",
            key="home_open_grammar",
            icon=":material/spellcheck:",
            width="stretch",
            on_click=navigate_to,
            args=("Grammar Checker",),
        )
    with middle_left:
        st.button(
            "Vocabulary",
            key="home_open_vocabulary",
            icon=":material/menu_book:",
            width="stretch",
            on_click=navigate_to,
            args=("Vocabulary",),
        )
    with middle_right:
        st.button(
            "My Mistakes",
            key="home_open_history",
            icon=":material/history:",
            width="stretch",
            on_click=navigate_to,
            args=("My Mistakes",),
        )
    with right:
        st.button(
            "Practice",
            key="home_open_practice",
            icon=":material/fitness_center:",
            width="stretch",
            on_click=navigate_to,
            args=("Practice",),
        )

    st.subheader("Recent activity")
    if recent_checks:
        latest = recent_checks[0]
        with st.container(border=True):
            error_count = len(latest.errors)
            mistake_word = "mistake" if error_count == 1 else "mistakes"
            status_label = "Correct" if latest.is_correct else f"Review {error_count} {mistake_word}"
            render_status_badge(
                status_label,
                tone="success" if latest.is_correct else "warning",
            )
            st.markdown(f"**{latest.original_sentence}**")
            st.caption(format_activity_time(latest.created_at))
            st.button(
                "Open learning history",
                key="home_recent_history",
                icon=":material/arrow_forward:",
                on_click=navigate_to,
                args=("My Mistakes",),
            )
    else:
        render_empty_state(
            "No learning history yet",
            "Check a Finnish sentence and your recent activity will appear here.",
        )

