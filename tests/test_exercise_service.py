import unicodedata

import pytest

from app.models.exercise import (
    Exercise,
    ExerciseDifficulty,
    ExerciseSelectionSource,
    ExerciseSource,
    ExerciseType,
    ExerciseValidationError,
    exercise_response_schema,
)
from app.models.grammar import ErrorType
from app.models.grammar import GrammarError, GrammarResult
from app.models.learner import LearnerProfile, LearnerWeakness
from app.services.database_service import DatabaseService
from app.services.exercise_service import (
    ExerciseService,
    ExerciseServiceError,
    ExerciseTargetUnavailableError,
)
from app.services.llm_service import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.services.profile_service import ProfileService


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request_json(self, *, system_prompt, user_payload, response_schema):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "response_schema": response_schema,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeProfileService:
    def __init__(self, profile):
        self.profile = profile
        self.learner_ids = []

    def get_profile(self, learner_id):
        self.learner_ids.append(learner_id)
        return self.profile


def profile(*weaknesses):
    return LearnerProfile(
        learner_id="demo_user",
        total_checks=sum(item.count for item in weaknesses),
        total_errors=sum(item.count for item in weaknesses),
        weaknesses=tuple(weaknesses),
    )


def weakness(error_type, count, percentage=None):
    return LearnerWeakness(
        error_type=error_type,
        count=count,
        percentage=float(percentage if percentage is not None else count),
    )


def provider_response(
    *,
    error_type="VERB_CONJUGATION",
    options=None,
    correct_answer="menen",
    question="Valitse oikea muoto: Minä ___ kouluun.",
    explanation="Minä-subjektin kanssa käytetään yksikön ensimmäistä persoonaa.",
):
    return {
        "schema_version": "1.0",
        "error_type": error_type,
        "exercise_type": "MULTIPLE_CHOICE",
        "difficulty": "BASIC",
        "question": question,
        "options": options or ["menee", "menen", "menet", "mennä"],
        "correct_answer": correct_answer,
        "explanation": explanation,
    }


def test_target_selection_uses_highest_supported_profile_weakness():
    learner_profile = profile(
        weakness(ErrorType.WORD_ORDER, 10),
        weakness(ErrorType.CASE_ERROR, 4),
        weakness(ErrorType.VERB_CONJUGATION, 3),
    )
    target, source = ExerciseService.select_target(learner_profile)
    assert target is ErrorType.CASE_ERROR
    assert source is ExerciseSelectionSource.LEARNER_PROFILE


def test_ties_are_deterministic_by_canonical_error_name():
    learner_profile = profile(
        weakness(ErrorType.VERB_CONJUGATION, 5),
        weakness(ErrorType.CASE_ERROR, 5),
    )
    target, _ = ExerciseService.select_target(learner_profile)
    assert target is ErrorType.CASE_ERROR


def test_no_history_requires_explicit_supported_topic():
    with pytest.raises(ExerciseTargetUnavailableError, match="no supported"):
        ExerciseService.select_target(profile())
    target, source = ExerciseService.select_target(profile(), ErrorType.CASE_ERROR)
    assert target is ErrorType.CASE_ERROR
    assert source is ExerciseSelectionSource.USER_SELECTED


def test_unsupported_topics_are_rejected_even_when_explicit():
    with pytest.raises(ExerciseTargetUnavailableError, match="not supported"):
        ExerciseService.select_target(profile(), ErrorType.WORD_ORDER)
    with pytest.raises(ExerciseTargetUnavailableError, match="not supported"):
        ExerciseService.select_target(profile(), ErrorType.OTHER)


def test_valid_generation_propagates_profile_target_and_metadata():
    profile_service = FakeProfileService(
        profile(weakness(ErrorType.VERB_CONJUGATION, 5, 62.5), weakness(ErrorType.CASE_ERROR, 3, 37.5))
    )
    client = FakeClient([provider_response()])
    service = ExerciseService(profile_service, client)
    exercise = service.generate_for_learner("demo_user")

    assert isinstance(exercise, Exercise)
    assert exercise.error_type is ErrorType.VERB_CONJUGATION
    assert exercise.exercise_type is ExerciseType.MULTIPLE_CHOICE
    assert exercise.difficulty is ExerciseDifficulty.BASIC
    assert exercise.selection_source is ExerciseSelectionSource.LEARNER_PROFILE
    assert exercise.metadata == {"weakness_count": 5, "weakness_percentage": 62.5}
    assert exercise.exercise_id.startswith("sha256:")
    assert client.calls[0]["user_payload"]["target_error_type"] == "VERB_CONJUGATION"
    assert "{{RESPONSE_SCHEMA}}" not in client.calls[0]["system_prompt"]
    assert profile_service.learner_ids == ["demo_user"]


def test_actual_phase7_profile_drives_exercise_target(tmp_path):
    database = DatabaseService(tmp_path / "history.db")
    database.initialize()
    grammar_result = GrammarResult(
        original_sentence="Minä menee kouluun.",
        is_correct=False,
        corrected_sentence="Minä menen kouluun.",
        errors=(
            GrammarError(
                text="menee",
                correction="menen",
                error_type=ErrorType.VERB_CONJUGATION,
                explanation="The verb agrees with the subject.",
                confidence=0.9,
            ),
        ),
        overall_explanation="The verb form is incorrect.",
        learning_tip="Check the person of the verb.",
    )
    database.save_grammar_result("demo_user", grammar_result)
    client = FakeClient([provider_response()])
    service = ExerciseService(ProfileService(database), client)

    exercise = service.generate_for_learner("demo_user")

    assert exercise.error_type is ErrorType.VERB_CONJUGATION
    assert client.calls[0]["user_payload"]["target_error_type"] == "VERB_CONJUGATION"


def test_explicit_topic_is_supported_without_history():
    client = FakeClient([provider_response(error_type="CASE_ERROR")])
    service = ExerciseService(FakeProfileService(profile()), client)
    exercise = service.generate_for_learner("demo_user", error_type="CASE_ERROR")
    assert exercise.error_type is ErrorType.CASE_ERROR
    assert exercise.selection_source is ExerciseSelectionSource.USER_SELECTED
    assert exercise.metadata["weakness_count"] == 0


def test_invalid_first_response_gets_one_repair_retry():
    invalid = provider_response(options=["menee", "menee", "menet", "mennä"])
    client = FakeClient([invalid, provider_response()])
    service = ExerciseService(FakeProfileService(profile(weakness(ErrorType.VERB_CONJUGATION, 1))), client)
    exercise = service.generate_for_learner("demo_user")
    assert exercise.correct_answer == "menen"
    assert len(client.calls) == 2
    assert "previous response was invalid" in client.calls[1]["system_prompt"]


@pytest.mark.parametrize(
    "bad_response, message",
    [
        (provider_response(options=["menee", "menet", "mennä", "tulla"]), "schema validation"),
        (provider_response(correct_answer="tulen"), "schema validation"),
        (provider_response(error_type="WORD_ORDER"), "schema validation"),
    ],
)
def test_invalid_exercise_is_rejected_without_repair_when_disabled(bad_response, message):
    client = FakeClient([bad_response])
    service = ExerciseService(
        FakeProfileService(profile(weakness(ErrorType.VERB_CONJUGATION, 1))),
        client,
        allow_repair_retry=False,
    )
    with pytest.raises(ExerciseServiceError, match=message):
        service.generate_for_learner("demo_user")


def test_unknown_provider_fields_are_rejected():
    raw = provider_response()
    raw["exercise_id"] = "provider-controlled"
    with pytest.raises(ExerciseValidationError, match="unsupported fields"):
        Exercise.from_provider_dict(raw, expected_error_type=ErrorType.VERB_CONJUGATION)


@pytest.mark.parametrize(
    "field, replacement",
    [
        ("correct_answer", None),
        ("exercise_type", "FILL_IN_THE_BLANK"),
        ("difficulty", "INTERMEDIATE"),
    ],
)
def test_missing_or_mismatched_required_generation_fields_are_rejected(field, replacement):
    raw = provider_response()
    if replacement is None:
        del raw[field]
    else:
        raw[field] = replacement
    with pytest.raises(ExerciseValidationError):
        Exercise.from_provider_dict(raw, expected_error_type=ErrorType.VERB_CONJUGATION)


def test_content_hash_cannot_be_replaced_after_validation():
    exercise = Exercise.from_provider_dict(
        provider_response(),
        expected_error_type=ErrorType.VERB_CONJUGATION,
    )
    values = exercise.to_dict()
    values["exercise_id"] = "provider-controlled"
    values["options"] = tuple(values["options"])
    values["error_type"] = ErrorType(values["error_type"])
    values["exercise_type"] = ExerciseType(values["exercise_type"])
    values["difficulty"] = ExerciseDifficulty(values["difficulty"])
    values["source"] = ExerciseSource(values["source"])
    values["selection_source"] = ExerciseSelectionSource(values["selection_source"])
    with pytest.raises(ExerciseValidationError, match="content hash"):
        Exercise(**values)


@pytest.mark.parametrize(
    "failure",
    [
        LLMConfigurationError("private"),
        LLMAuthenticationError("private"),
        LLMRateLimitError("private"),
        LLMTimeoutError("private"),
    ],
)
def test_provider_failures_are_safe_and_not_repaired(failure):
    client = FakeClient([failure])
    service = ExerciseService(
        FakeProfileService(profile(weakness(ErrorType.VERB_CONJUGATION, 1))),
        client,
    )
    with pytest.raises(ExerciseServiceError) as exc_info:
        service.generate_for_learner("demo_user")
    assert "private" not in str(exc_info.value)
    assert len(client.calls) == 1


def test_malformed_provider_json_can_be_repaired_once():
    client = FakeClient([LLMResponseError("private JSON detail"), provider_response()])
    service = ExerciseService(
        FakeProfileService(profile(weakness(ErrorType.VERB_CONJUGATION, 1))),
        client,
    )
    result = service.generate_for_learner("demo_user")
    assert result.exercise_type is ExerciseType.MULTIPLE_CHOICE
    assert len(client.calls) == 2


def test_answer_checking_is_deterministic_for_text_labels_indices_and_whitespace():
    client = FakeClient([provider_response()])
    service = ExerciseService(FakeProfileService(profile(weakness(ErrorType.VERB_CONJUGATION, 1))), client)
    exercise = service.generate_for_learner("demo_user")

    assert service.check_answer(exercise, "B").is_correct is True
    assert service.check_answer(exercise, "  menen  ").is_correct is True
    assert service.check_answer(exercise, 1).is_correct is True
    assert service.check_answer(exercise, "menee").is_correct is False
    with pytest.raises(ExerciseServiceError, match="option label"):
        service.check_answer(exercise, "")
    with pytest.raises(ExerciseServiceError, match="option label"):
        service.check_answer(exercise, "unrelated answer")


@pytest.mark.parametrize(
    "error_type, question, options, correct_answer",
    [
        (
            ErrorType.CASE_ERROR,
            "Valitse oikea muoto: Asun ___.",
            ["Helsingissä", "Helsinkiin", "Helsingistä", "Helsinki"],
            "Helsingissä",
        ),
        (
            ErrorType.VERB_CONJUGATION,
            "Valitse oikea muoto: Minä ___ kouluun.",
            ["menee", "menen", "menet", "mennä"],
            "menen",
        ),
        (
            ErrorType.NOUN_INFLECTION,
            "Mikä on sanan 'lapsi' monikon perusmuoto?",
            ["lapset", "lapsi", "lapsia", "lapsen"],
            "lapset",
        ),
        (
            ErrorType.AGREEMENT,
            "Valitse sopiva muoto: ___ talot ovat uusia.",
            ["Suuret", "Suuri", "Suurta", "Suuren"],
            "Suuret",
        ),
        (
            ErrorType.SPELLING,
            "Mikä sana on kirjoitettu oikein?",
            ["yö", "yo", "yöä", "öy"],
            "yö",
        ),
    ],
)
def test_all_supported_categories_accept_valid_structured_exercises(
    error_type, question, options, correct_answer
):
    raw = provider_response(
        error_type=error_type.value,
        question=question,
        options=options,
        correct_answer=correct_answer,
        explanation="Valitse pyydettyyn kielioppikohtaan sopiva muoto.",
    )
    client = FakeClient([raw])
    service = ExerciseService(FakeProfileService(profile(weakness(error_type, 1))), client)

    exercise = service.generate_for_learner("demo_user")

    assert exercise.error_type is error_type
    assert exercise.correct_answer == correct_answer
    assert client.calls[0]["user_payload"]["target_error_type"] == error_type.value


def test_answer_matching_remains_case_sensitive():
    client = FakeClient([provider_response()])
    service = ExerciseService(
        FakeProfileService(profile(weakness(ErrorType.VERB_CONJUGATION, 1))),
        client,
    )
    exercise = service.generate_for_learner("demo_user")
    with pytest.raises(ExerciseServiceError, match="option label"):
        service.check_answer(exercise, "MENEN")


def test_unicode_and_capitalization_are_not_stripped_from_exercise_content():
    raw = provider_response(
        error_type="SPELLING",
        options=["Äiti", "äiti", "koulu", "kouluun"],
        correct_answer="Äiti",
        question="Valitse sana: Äiti käy koulussa.",
        explanation="Säilytä suomen kielen ä-kirjain.",
    )
    client = FakeClient([raw])
    service = ExerciseService(FakeProfileService(profile(weakness(ErrorType.SPELLING, 1))), client)
    exercise = service.generate_for_learner("demo_user")
    assert exercise.options[0] == "Äiti"
    assert exercise.correct_answer == "Äiti"
    assert unicodedata.normalize("NFC", exercise.question) == exercise.question


def test_exercise_ids_are_reproducible_for_same_validated_content():
    first = Exercise.from_provider_dict(provider_response(), expected_error_type=ErrorType.VERB_CONJUGATION)
    second = Exercise.from_provider_dict(provider_response(), expected_error_type=ErrorType.VERB_CONJUGATION)
    assert first.exercise_id == second.exercise_id
    assert first.to_dict() == second.to_dict()


def test_response_schema_is_strict_and_only_allows_supported_mvp_format():
    schema = exercise_response_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["options"]["minItems"] == 4
    assert "WORD_ORDER" not in schema["properties"]["error_type"]["enum"]
