"""Learner history and weakness-profile page."""

from __future__ import annotations

import streamlit as st

from app.services.database_service import DatabaseError, DatabaseService, DEFAULT_LEARNER_ID
from app.services.profile_service import ProfileService
from app.ui.common import error_type_label, profile_rows
from app.ui.services import get_database_service, get_profile_service


def render_history_page(
    *,
    learner_id: str = DEFAULT_LEARNER_ID,
    database_service: DatabaseService | None = None,
    profile_service: ProfileService | None = None,
) -> None:
    """Render fresh learner history/profile data without caching user state."""

    st.title("My Mistakes")
    st.write("Review recent grammar checks and see which error types recur most often.")
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
    metrics[0].metric("Grammar checks", profile.total_checks)
    metrics[1].metric("Detected errors", profile.total_errors)
    metrics[2].metric(
        "Primary weakness",
        error_type_label(profile.primary_weakness) if profile.primary_weakness else "None yet",
    )

    st.subheader("Weakness profile")
    if profile.weaknesses:
        st.dataframe(profile_rows(profile), hide_index=True, width="stretch")
    else:
        st.info("No recurring grammar errors yet. Check some Finnish sentences to build your profile.")

    st.subheader("Recent checks")
    if not checks:
        st.info("Check some Finnish sentences to start building your learning profile.")
        return
    for check in checks:
        label = f"{check.created_at} — {check.original_sentence}"
        with st.expander(label):
            st.write(f"**Corrected:** {check.corrected_sentence}")
            st.write("**Status:** " + ("Correct" if check.is_correct else "Errors detected"))
            if check.errors:
                for error in check.errors:
                    st.write(
                        f"**{error_type_label(error.error_type)}:** "
                        f"{error.error_text} → {error.correction}"
                    )
                    st.caption(error.explanation)
            else:
                st.caption("No error records were stored for this check.")
