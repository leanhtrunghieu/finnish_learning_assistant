"""Personalized-practice page with explicit generation and answer actions."""

from __future__ import annotations

import streamlit as st

from app.models.exercise import (
    Exercise,
    ExerciseAttemptResult,
    SUPPORTED_GENERATION_ERROR_TYPES,
)
from app.models.grammar import ErrorType
from app.services.database_service import DatabaseError, DEFAULT_LEARNER_ID
from app.services.exercise_service import ExerciseService, ExerciseServiceError, ExerciseTargetUnavailableError
from app.services.profile_service import ProfileService
from app.ui.common import clear_practice_state, error_type_label
from app.ui.services import get_exercise_service, get_profile_service
from app.ui.theme import render_empty_state, render_eyebrow


def _supported_topic_label(error_type: ErrorType) -> str:
    return error_type_label(error_type)


def _render_attempt(attempt: ExerciseAttemptResult) -> None:
    if attempt.is_correct:
        st.success("Correct answer!", icon="✅")
    else:
        st.error("Not quite — review the answer below.", icon="❌")
    with st.container(border=True):
        st.markdown(f"**Correct answer:** {attempt.correct_answer}")
        st.write(attempt.explanation)


def render_practice_page(
    *,
    learner_id: str = DEFAULT_LEARNER_ID,
    exercise_service: ExerciseService | None = None,
    profile_service: ProfileService | None = None,
) -> None:
    """Render profile-driven practice while keeping the exercise in session state."""

    render_eyebrow("Strengthen a pattern")
    st.title("Practice")
    st.write("Generate a focused exercise based on the grammar pattern that needs the most attention.")
    try:
        profile = (profile_service or get_profile_service()).get_profile(learner_id)
    except DatabaseError:
        st.error("Your learner profile is temporarily unavailable.")
        return
    except Exception:
        st.error("Your learner profile could not be loaded.")
        return

    supported_primary = next(
        (
            weakness.error_type
            for weakness in profile.weaknesses
            if weakness.error_type in SUPPORTED_GENERATION_ERROR_TYPES
        ),
        None,
    )
    requested_topic = st.session_state.get("practice_requested_topic")
    if requested_topic in SUPPORTED_GENERATION_ERROR_TYPES:
        with st.container(border=True):
            st.caption("CHOSEN FROM YOUR GRAMMAR FEEDBACK")
            st.markdown(f"### {error_type_label(requested_topic)}")
            st.write("Generate an exercise to practise the pattern you just reviewed.")
        selected_topic = requested_topic
    elif supported_primary is not None:
        with st.container(border=True):
            st.caption("CURRENT PRACTICE FOCUS")
            st.markdown(f"### {error_type_label(supported_primary)}")
            st.write("This focus comes from the mistakes in your learning history.")
        selected_topic: ErrorType | None = None
    else:
        st.info("Your history does not show a practice focus yet. Choose a topic to begin.")
        selected_topic = st.selectbox(
            "Practice topic",
            options=list(SUPPORTED_GENERATION_ERROR_TYPES),
            format_func=_supported_topic_label,
            key="practice_topic",
        )

    current = st.session_state.get("practice_exercise")
    button_label = "Generate an exercise" if not isinstance(current, Exercise) else "Generate a new exercise"
    if st.button(
        button_label,
        type="primary",
        key="generate_practice",
        icon=":material/auto_awesome:",
        width="stretch",
    ):
        try:
            service = exercise_service or get_exercise_service()
            with st.spinner("Generating a Finnish practice exercise…"):
                exercise = service.generate_for_learner(
                    learner_id,
                    error_type=selected_topic,
                )
        except ExerciseTargetUnavailableError as exc:
            clear_practice_state()
            st.session_state["practice_generation_error"] = str(exc)
        except ExerciseServiceError as exc:
            clear_practice_state()
            st.session_state["practice_generation_error"] = str(exc)
        except Exception:
            clear_practice_state()
            st.session_state["practice_generation_error"] = (
                "Practice generation is temporarily unavailable. Please try again later."
            )
        else:
            st.session_state["practice_exercise"] = exercise
            st.session_state["practice_attempt"] = None
            st.session_state["practice_generation_error"] = None

    if st.session_state.get("practice_generation_error"):
        st.warning(st.session_state["practice_generation_error"])

    exercise = st.session_state.get("practice_exercise")
    if not isinstance(exercise, Exercise):
        render_empty_state(
            "Your next exercise will appear here",
            "Generate an exercise when you are ready to practise.",
        )
        return
    st.subheader(f"{error_type_label(exercise.error_type)} practice")
    st.caption("Choose the best answer. Your exercise stays in place until you request a new one.")
    with st.container(border=True):
        st.markdown(f"### {exercise.question}")
        answer = st.radio(
            "Choose an answer",
            options=list(exercise.options),
            index=None,
            key=f"practice_answer_{exercise.exercise_id}",
        )
        check_answer = st.button(
            "Check Answer",
            key=f"check_answer_{exercise.exercise_id}",
            type="primary",
            icon=":material/check_circle:",
            disabled=answer is None,
            width="stretch",
        )
    if check_answer and answer is not None:
        try:
            service = exercise_service or get_exercise_service()
            st.session_state["practice_attempt"] = service.check_answer(exercise, answer)
        except ExerciseServiceError:
            st.error("That answer could not be checked. Choose one of the listed options and try again.")
    attempt = st.session_state.get("practice_attempt")
    if isinstance(attempt, ExerciseAttemptResult):
        _render_attempt(attempt)
