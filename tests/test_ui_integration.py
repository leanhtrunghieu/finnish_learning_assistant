"""Focused tests for Phase 10 UI orchestration and rerun-safe boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.models.exercise import (
    Exercise,
    ExerciseAttemptResult,
    ExerciseDifficulty,
    ExerciseSelectionSource,
    ExerciseType,
)
from app.models.grammar import ErrorType, GrammarError, GrammarResult
from app.models.learner import LearnerProfile, LearnerWeakness
from app.services.database_service import DatabaseService
from app.services.profile_service import ProfileService
from app.ui.common import error_type_label, format_activity_time, profile_rows
from app.ui.grammar_page import analyze_and_persist
from app.ui.home import APP_DESCRIPTION


def _correct_result(sentence: str = "Minä menen kouluun.") -> GrammarResult:
    return GrammarResult(
        original_sentence=sentence,
        is_correct=True,
        corrected_sentence=sentence,
        errors=(),
        overall_explanation="The sentence is grammatically correct.",
        learning_tip="Keep checking agreement and case in new sentences.",
    )


@dataclass
class _FakeGrammarService:
    calls: int = 0

    def check_sentence(self, sentence: str, *, language_mode: object) -> GrammarResult:
        self.calls += 1
        return _correct_result(sentence)


@dataclass
class _FixedGrammarService:
    result: GrammarResult
    calls: int = 0

    def check_sentence(self, sentence: str, *, language_mode: object) -> GrammarResult:
        self.calls += 1
        assert sentence == self.result.original_sentence
        return self.result


@dataclass
class _FakeDatabaseService:
    calls: int = 0

    def save_grammar_result(self, learner_id: str, result: GrammarResult) -> int:
        self.calls += 1
        assert learner_id == "demo_user"
        assert result.is_correct
        return 17


def _render_grammar_test_page(grammar_service: object, database_service: object) -> None:
    from app.config import Settings
    from app.ui.common import initialize_session_state
    from app.ui.grammar_page import render_grammar_page

    initialize_session_state()
    render_grammar_page(
        settings=Settings(
            app_title="Finnish Learning Assistant",
            environment="test",
            log_level="INFO",
            llm_api_key=None,
            llm_api_base_url=None,
            llm_model=None,
        ),
        grammar_service=grammar_service,
        database_service=database_service,
    )


def _exercise() -> Exercise:
    return Exercise.from_provider_dict(
        {
            "schema_version": "1.0",
            "error_type": "VERB_CONJUGATION",
            "exercise_type": "MULTIPLE_CHOICE",
            "difficulty": "BASIC",
            "question": "Choose the correct form: Minä ___ kouluun.",
            "options": ["menen", "menee", "menet", "mennä"],
            "correct_answer": "menen",
            "explanation": "Minä requires the first-person singular form.",
        },
        expected_error_type=ErrorType.VERB_CONJUGATION,
        expected_exercise_type=ExerciseType.MULTIPLE_CHOICE,
        expected_difficulty=ExerciseDifficulty.BASIC,
        selection_source=ExerciseSelectionSource.LEARNER_PROFILE,
    )


@dataclass
class _FakeProfileService:
    profile: LearnerProfile

    def get_profile(self, learner_id: str) -> LearnerProfile:
        assert learner_id == "demo_user"
        return self.profile


@dataclass
class _FakeExerciseService:
    generate_calls: int = 0
    check_calls: int = 0
    generated: Exercise = _exercise()
    expected_error_type: ErrorType | None = None

    def generate_for_learner(self, learner_id: str, *, error_type: object = None) -> Exercise:
        self.generate_calls += 1
        assert learner_id == "demo_user"
        assert error_type is self.expected_error_type
        return self.generated

    def check_answer(self, exercise: Exercise, answer: str) -> ExerciseAttemptResult:
        self.check_calls += 1
        return ExerciseAttemptResult(
            exercise_id=exercise.exercise_id,
            user_answer=answer,
            correct_answer=exercise.correct_answer,
            is_correct=answer == exercise.correct_answer,
            explanation=exercise.explanation,
        )


def _render_practice_test_page(profile_service: object, exercise_service: object) -> None:
    from app.ui.common import initialize_session_state
    from app.ui.practice_page import render_practice_page

    initialize_session_state()
    render_practice_page(
        profile_service=profile_service,
        exercise_service=exercise_service,
    )


def _render_requested_practice_test_page(
    profile_service: object,
    exercise_service: object,
    requested_topic: object,
) -> None:
    import streamlit as st

    from app.ui.common import initialize_session_state
    from app.ui.practice_page import render_practice_page

    initialize_session_state()
    st.session_state["practice_requested_topic"] = requested_topic
    render_practice_page(
        profile_service=profile_service,
        exercise_service=exercise_service,
    )


def test_error_type_labels_are_centralized() -> None:
    assert error_type_label(ErrorType.VERB_CONJUGATION) == "Verb conjugation"
    assert error_type_label("CASE_ERROR") == "Case error"
    assert error_type_label("future_category") == "Future Category"


def test_profile_rows_are_learner_friendly() -> None:
    class Weakness:
        error_type = ErrorType.CASE_ERROR
        count = 3
        percentage = 75.0

    class Profile:
        weaknesses = (Weakness(),)

    assert profile_rows(Profile()) == [
        {"Error type": "Case error", "Count": 3, "Percentage": "75%"}
    ]


def test_activity_time_is_readable_without_guessing_naive_timezone() -> None:
    assert format_activity_time("2026-09-20T01:26:43Z") == "20 Sep 2026, 01:26 UTC"
    assert format_activity_time("2026-09-20T01:26:43") == "20 Sep 2026, 01:26"


def test_explicit_grammar_action_persists_once() -> None:
    grammar = _FakeGrammarService()
    database = _FakeDatabaseService()
    result, check_id, save_error = analyze_and_persist(
        "Minä menen kouluun.",
        language_mode=object(),
        learner_id="demo_user",
        grammar_service=grammar,
        database_service=database,
    )
    assert result.is_correct
    assert check_id == 17
    assert save_error is None
    assert grammar.calls == 1
    assert database.calls == 1


def test_streamlit_shell_exposes_all_phase_10_pages() -> None:
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception
    assert not app.error
    assert [option for option in app.sidebar.radio[0].options] == [
        "Home",
        "Grammar Checker",
        "Vocabulary",
        "My Mistakes",
        "Practice",
        "About",
    ]
    assert "Finnish learners" in APP_DESCRIPTION


def test_local_about_page_loads_without_llm_credentials() -> None:
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    app.sidebar.radio[0].set_value("About").run()
    assert not app.exception
    assert any("About" in title.value for title in app.title)
    assert not app.error


def test_every_navigation_page_renders_without_an_action_side_effect() -> None:
    for page in ("Home", "Grammar Checker", "Vocabulary", "My Mistakes", "Practice", "About"):
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
        assert not app.error, page


def test_empty_grammar_submission_is_handled_before_provider_call() -> None:
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    app.sidebar.radio[0].set_value("Grammar Checker").run()
    app.button[0].click().run()
    assert not app.exception
    assert any("Enter a Finnish sentence first." in warning.value for warning in app.warning)


def test_grammar_submission_does_not_repeat_analysis_or_persistence_on_rerun(tmp_path: Path) -> None:
    grammar = _FakeGrammarService()
    database = DatabaseService(tmp_path / "correct-ui-integration.db")
    database.initialize()
    app = AppTest.from_function(
        _render_grammar_test_page,
        args=(grammar, database),
    ).run()

    app.text_area[0].set_value("Minä menen kouluun.").run()
    app.button[0].click().run()
    assert grammar.calls == 1
    assert database.count_grammar_checks("demo_user") == 1
    assert app.session_state["grammar_check_id"] == 1

    app.run()
    assert grammar.calls == 1
    assert database.count_grammar_checks("demo_user") == 1
    assert database.get_learner_errors("demo_user") == ()
    assert ProfileService(database).get_profile("demo_user").total_errors == 0
    assert any("No grammar errors detected" in item.value for item in app.success)


def test_practice_exercise_and_answer_survive_streamlit_reruns() -> None:
    profile = LearnerProfile(
        learner_id="demo_user",
        total_checks=2,
        total_errors=1,
        weaknesses=(
            LearnerWeakness(
                error_type=ErrorType.VERB_CONJUGATION,
                count=1,
                percentage=100.0,
            ),
        ),
    )
    profile_service = _FakeProfileService(profile)
    exercise_service = _FakeExerciseService()
    app = AppTest.from_function(
        _render_practice_test_page,
        args=(profile_service, exercise_service),
    ).run()

    app.button[0].click().run()
    exercise_id = app.session_state["practice_exercise"].exercise_id
    assert exercise_service.generate_calls == 1

    app.run()
    assert app.radio[0].value is None
    check_button = next(button for button in app.button if button.label == "Check Answer")
    assert check_button.disabled

    app.radio[0].set_value("menen").run()
    assert exercise_service.generate_calls == 1
    assert app.session_state["practice_exercise"].exercise_id == exercise_id

    check_button = next(button for button in app.button if button.label == "Check Answer")
    assert not check_button.disabled
    check_button.click().run()
    assert exercise_service.generate_calls == 1
    assert exercise_service.check_calls == 1
    assert app.session_state["practice_exercise"].exercise_id == exercise_id
    assert app.session_state["practice_attempt"].is_correct
    assert any("Correct answer!" in item.value for item in app.success)
    assert any("Correct answer:" in item.value for item in app.markdown)


def test_practice_uses_topic_requested_from_grammar_feedback() -> None:
    profile = LearnerProfile(
        learner_id="demo_user",
        total_checks=1,
        total_errors=1,
        weaknesses=(
            LearnerWeakness(
                error_type=ErrorType.VERB_CONJUGATION,
                count=1,
                percentage=100.0,
            ),
        ),
    )
    profile_service = _FakeProfileService(profile)
    exercise_service = _FakeExerciseService(expected_error_type=ErrorType.CASE_ERROR)
    app = AppTest.from_function(
        _render_requested_practice_test_page,
        args=(profile_service, exercise_service, ErrorType.CASE_ERROR),
    ).run()

    app.button[0].click().run()

    assert exercise_service.generate_calls == 1
    assert app.session_state["practice_requested_topic"] is ErrorType.CASE_ERROR


def test_incorrect_multi_error_result_is_rendered_and_persisted_once(tmp_path: Path) -> None:
    result = GrammarResult(
        original_sentence="Minä menee koulu.",
        is_correct=False,
        corrected_sentence="Minä menen kouluun.",
        errors=(
            GrammarError(
                text="menee",
                correction="menen",
                error_type=ErrorType.VERB_CONJUGATION,
                explanation="The verb must agree with minä.",
                confidence=0.98,
            ),
            GrammarError(
                text="koulu",
                correction="kouluun",
                error_type=ErrorType.CASE_ERROR,
                explanation="Movement toward a destination uses the illative case here.",
                confidence=0.96,
            ),
        ),
        overall_explanation="The sentence has two grammar errors.",
        learning_tip="Check subject–verb agreement and destination cases.",
    )
    grammar = _FixedGrammarService(result)
    database = DatabaseService(tmp_path / "ui-integration.db")
    database.initialize()
    app = AppTest.from_function(
        _render_grammar_test_page,
        args=(grammar, database),
    ).run()

    app.text_area[0].set_value(result.original_sentence).run()
    app.button[0].click().run()
    app.run()

    assert grammar.calls == 1
    assert database.count_grammar_checks("demo_user") == 1
    assert len(database.get_learner_errors("demo_user")) == 2
    profile = ProfileService(database).get_profile("demo_user")
    assert profile.total_errors == 2
    assert {item.error_type for item in profile.weaknesses} == {
        ErrorType.CASE_ERROR,
        ErrorType.VERB_CONJUGATION,
    }
    rendered = " ".join(item.value for item in app.markdown)
    assert "Verb conjugation" in rendered
    assert "Case error" in rendered
    assert "Minä menen kouluun." in rendered

    practice_button = next(button for button in app.button if button.label == "Practice this pattern")
    practice_button.click().run()
    assert app.session_state["nav_page"] == "Practice"
    assert app.session_state["practice_requested_topic"] is ErrorType.VERB_CONJUGATION
