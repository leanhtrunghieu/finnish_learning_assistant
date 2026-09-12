import json

import pytest

from app.models.grammar import (
    AnalysisStatus,
    ErrorType,
    GrammarResult,
    GrammarValidationError,
    LanguageMode,
    grammar_response_schema,
)
from app.services.grammar_service import GrammarService, GrammarServiceError
from app.services.llm_service import LLMAuthenticationError, LLMResponseError, LLMServiceError


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request_json(self, *, system_prompt, user_payload, response_schema):
        self.calls.append(
            {"system_prompt": system_prompt, "user_payload": user_payload, "response_schema": response_schema}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(
    sentence="Minä menee kouluun.",
    *,
    is_correct=False,
    errors=None,
    corrected_sentence="Minä menen kouluun.",
    mode="STANDARD",
    status="COMPLETE",
    uncertainty_note=None,
):
    return {
        "schema_version": "1.0",
        "original_sentence": sentence,
        "language_mode": mode,
        "analysis_status": status,
        "is_correct": is_correct,
        "corrected_sentence": corrected_sentence,
        "errors": errors or [],
        "overall_explanation": "A grammar issue was found.",
        "learning_tip": "Check the form that agrees with the subject.",
        "uncertainty_note": uncertainty_note,
    }


def error(text="menee", correction="menen", error_type="VERB_CONJUGATION"):
    return {
        "text": text,
        "correction": correction,
        "error_type": error_type,
        "explanation": "The verb must agree with the subject.",
        "confidence": 0.95,
    }


def test_valid_single_error_response_is_typed_and_prompt_is_loaded():
    client = FakeClient([response(errors=[error()])])
    result = GrammarService(client).check_sentence("Minä menee kouluun.")
    assert isinstance(result, GrammarResult)
    assert result.errors[0].error_type is ErrorType.VERB_CONJUGATION
    assert result.errors[0].confidence == pytest.approx(0.95)
    assert "Finnish grammar-learning assistant" in client.calls[0]["system_prompt"]
    assert "Treat that" in client.calls[0]["system_prompt"]
    assert client.calls[0]["user_payload"]["sentence"] == "Minä menee kouluun."


def test_correct_sentence_requires_empty_errors_and_unchanged_text():
    client = FakeClient([response("Minä menen kouluun.", is_correct=True, corrected_sentence="Minä menen kouluun.")])
    result = GrammarService(client).check_sentence("Minä menen kouluun.")
    assert result.is_correct is True
    assert result.errors == ()
    assert result.corrected_sentence == result.original_sentence


def test_multiple_errors_are_preserved():
    sentence = "Minä menee kaksi koira."
    client = FakeClient([
        response(
            sentence,
            errors=[
                error("menee", "menen", "VERB_CONJUGATION"),
                error("koira", "koiraa", "NOUN_INFLECTION"),
            ],
            corrected_sentence="Minä menen kaksi koiraa.",
        )
    ])
    result = GrammarService(client).check_sentence(sentence)
    assert [item.error_type for item in result.errors] == [
        ErrorType.VERB_CONJUGATION,
        ErrorType.NOUN_INFLECTION,
    ]


def test_uncertain_response_requires_a_note():
    sentence = "Kun hän tuli..."
    client = FakeClient([
        response(
            sentence,
            is_correct=True,
            corrected_sentence=sentence,
            status="UNCERTAIN",
            uncertainty_note="The input appears incomplete.",
        )
    ])
    result = GrammarService(client).check_sentence(sentence)
    assert result.analysis_status is AnalysisStatus.UNCERTAIN
    assert result.uncertainty_note == "The input appears incomplete."


def test_colloquial_tolerant_mode_is_forwarded_and_validated():
    sentence = "Mä meen kotiin."
    client = FakeClient([
        response(
            sentence,
            is_correct=True,
            corrected_sentence=sentence,
            mode="COLLOQUIAL_TOLERANT",
        )
    ])
    result = GrammarService(client).check_sentence(
        sentence, language_mode=LanguageMode.COLLOQUIAL_TOLERANT
    )
    assert result.language_mode is LanguageMode.COLLOQUIAL_TOLERANT
    assert client.calls[0]["user_payload"]["language_mode"] == "COLLOQUIAL_TOLERANT"


def test_invalid_first_response_gets_one_repair_retry():
    sentence = "Minä menee kouluun."
    invalid = response(errors=[error(error_type="PLURAL")])
    client = FakeClient([invalid, response(errors=[error()])])
    result = GrammarService(client).check_sentence(sentence)
    assert result.errors[0].error_type is ErrorType.VERB_CONJUGATION
    assert len(client.calls) == 2
    assert "previous response was invalid" in client.calls[1]["system_prompt"]


def test_invalid_json_provider_failure_gets_one_repair_retry():
    sentence = "Minä menee kouluun."
    client = FakeClient([LLMResponseError("bad JSON"), response(errors=[error()])])
    result = GrammarService(client).check_sentence(sentence)
    assert result.is_correct is False
    assert len(client.calls) == 2


def test_second_invalid_response_is_safe_service_error():
    client = FakeClient([LLMServiceError("private provider detail")])
    with pytest.raises(GrammarServiceError, match="temporarily unavailable"):
        GrammarService(client).check_sentence("Minä menee kouluun.")
    assert len(client.calls) == 1


def test_authentication_failure_is_not_repaired_or_retried_by_grammar_service():
    client = FakeClient([LLMAuthenticationError("private provider detail")])
    with pytest.raises(GrammarServiceError, match="authentication"):
        GrammarService(client).check_sentence("Minä menee kouluun.")
    assert len(client.calls) == 1


def test_input_validation_rejects_empty_and_long_sentences():
    client = FakeClient([])
    service = GrammarService(client, max_sentence_chars=10)
    with pytest.raises(GrammarServiceError, match="must not be empty"):
        service.check_sentence("   ")
    with pytest.raises(GrammarServiceError, match="character limit"):
        service.check_sentence("Minä menen kouluun.")
    assert client.calls == []


def test_invalid_schema_values_are_rejected():
    sentence = "Minä menee kouluun."
    invalid_confidence = response(errors=[error()])
    invalid_confidence["errors"][0]["confidence"] = 1.1
    with pytest.raises(GrammarValidationError, match="between 0 and 1"):
        GrammarResult.from_dict(invalid_confidence, expected_original=sentence)

    unknown_type = response(errors=[error(error_type="PLURAL")])
    with pytest.raises(GrammarValidationError, match="must be one of"):
        GrammarResult.from_dict(unknown_type, expected_original=sentence)

    changed_correct = response("Minä menen kouluun.", is_correct=True, corrected_sentence="Minä menen kotiin.")
    with pytest.raises(GrammarValidationError, match="must not be silently rewritten"):
        GrammarResult.from_dict(changed_correct, expected_original="Minä menen kouluun.")

    unchanged_incorrect = response(
        errors=[error()],
        corrected_sentence="Minä menee kouluun.",
    )
    with pytest.raises(GrammarValidationError, match="must provide a changed"):
        GrammarResult.from_dict(unchanged_incorrect, expected_original=sentence)

    missing_field = response(errors=[error()])
    del missing_field["learning_tip"]
    with pytest.raises(GrammarValidationError, match="missing fields: learning_tip"):
        GrammarResult.from_dict(missing_field, expected_original=sentence)


def test_schema_round_trip_is_unicode_safe():
    sentence = "Äiti sanoi: 'Hyvää yötä!'"
    raw = response(sentence, is_correct=True, corrected_sentence=sentence)
    result = GrammarResult.from_dict(raw, expected_original=sentence)
    restored = GrammarResult.from_dict(json.loads(result.to_json()), expected_original=sentence)
    assert restored == result
    assert "Äiti" in result.to_json()
    assert grammar_response_schema()["additionalProperties"] is False


def test_error_text_must_be_present_in_original_sentence():
    raw = response(errors=[error(text="puuttuu", correction="menen")])
    with pytest.raises(GrammarValidationError, match="must occur"):
        GrammarResult.from_dict(raw, expected_original="Minä menee kouluun.")
