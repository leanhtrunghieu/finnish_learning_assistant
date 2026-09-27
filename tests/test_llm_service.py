import json

import pytest
import requests

from app.services.llm_service import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseError,
    LLMService,
    LLMSettings,
)


class FakeResponse:
    def __init__(self, status_code=200, content=None, headers=None):
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}

    def json(self):
        if isinstance(self._content, Exception):
            raise self._content
        return self._content


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def envelope(value, *, status_code=200, headers=None):
    return FakeResponse(
        status_code=status_code,
        content={"choices": [{"message": {"content": json.dumps(value, ensure_ascii=False)}}]},
        headers=headers,
    )


def settings(**overrides):
    values = dict(
        provider="openai_compatible",
        api_key="secret-key",
        base_url="https://llm.example/v1",
        model="test-model",
        max_retries=1,
    )
    values.update(overrides)
    return LLMSettings(**values)


def test_successful_json_request_builds_provider_payload_without_exposing_key():
    session = FakeSession([envelope({"ok": True})])
    result = LLMService(settings(), session=session, sleep_fn=lambda _: None).request_json(
        system_prompt="system",
        user_payload={"sentence": "Äiti sanoi hei."},
        response_schema={"type": "object"},
    )
    assert result == {"ok": True}
    args, kwargs = session.calls[0]
    assert args[0] == "https://llm.example/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-key"
    assert kwargs["json"]["messages"][1]["content"] == '{"sentence":"Äiti sanoi hei."}'
    assert kwargs["json"]["response_format"] == {"type": "json_object"}
    assert kwargs["json"]["max_completion_tokens"] == 800
    assert "max_tokens" not in kwargs["json"]


def test_gpt_5_6_uses_temperature_compatible_reasoning_mode():
    session = FakeSession([envelope({"ok": True})])
    LLMService(
        settings(model="gpt-5.6-luna", temperature=0.0),
        session=session,
        sleep_fn=lambda _: None,
    ).request_json(system_prompt="system", user_payload={}, response_schema={})
    payload = session.calls[0][1]["json"]
    assert payload["temperature"] == 0.0
    assert payload["reasoning_effort"] == "none"


def test_missing_api_key_fails_before_network_call():
    session = FakeSession([])
    with pytest.raises(LLMConfigurationError, match="API_KEY"):
        LLMService(settings(api_key=None), session=session).request_json(
            system_prompt="system", user_payload={}, response_schema={}
        )
    assert session.calls == []


def test_authentication_failure_is_not_retried():
    session = FakeSession([FakeResponse(status_code=401)])
    sleeps = []
    with pytest.raises(LLMAuthenticationError):
        LLMService(settings(), session=session, sleep_fn=sleeps.append).request_json(
            system_prompt="system", user_payload={}, response_schema={}
        )
    assert len(session.calls) == 1
    assert sleeps == []


def test_timeout_retries_once_then_succeeds():
    session = FakeSession([requests.Timeout(), envelope({"ok": True})])
    sleeps = []
    result = LLMService(settings(), session=session, sleep_fn=sleeps.append).request_json(
        system_prompt="system", user_payload={}, response_schema={}
    )
    assert result == {"ok": True}
    assert len(session.calls) == 2
    assert sleeps == [pytest.approx(0.25)]


def test_rate_limit_retries_once_then_succeeds():
    session = FakeSession([
        FakeResponse(status_code=429, headers={"Retry-After": "1"}),
        envelope({"ok": True}),
    ])
    sleeps = []
    result = LLMService(settings(), session=session, sleep_fn=sleeps.append).request_json(
        system_prompt="system", user_payload={}, response_schema={}
    )
    assert result == {"ok": True}
    assert sleeps == [pytest.approx(1.0)]


def test_provider_4xx_is_controlled_without_retry():
    session = FakeSession([
        FakeResponse(
            status_code=400,
            content={"error": {"type": "invalid_request_error", "code": "bad_field", "message": "Bad field"}},
            headers={"x-request-id": "req_safe"},
        )
    ])
    with pytest.raises(LLMProviderError, match="rejected") as captured:
        LLMService(settings(), session=session).request_json(
            system_prompt="system", user_payload={}, response_schema={}
        )
    assert len(session.calls) == 1
    assert captured.value.diagnostic.to_safe_dict() == {
        "stage": "provider_http",
        "exception_class": "LLMProviderError",
        "http_status": 400,
        "provider_error_type": "invalid_request_error",
        "provider_error_code": "bad_field",
        "provider_message": "Bad field",
        "request_id": "req_safe",
    }


def test_malformed_provider_envelope_and_message_json_are_rejected():
    with pytest.raises(LLMResponseError, match="message content"):
        LLMService(settings(), session=FakeSession([FakeResponse(content={})])).request_json(
            system_prompt="system", user_payload={}, response_schema={}
        )
    malformed = FakeResponse(
        content={"choices": [{"message": {"content": "not JSON"}}]}
    )
    with pytest.raises(LLMResponseError, match="not valid JSON"):
        LLMService(settings(), session=FakeSession([malformed])).request_json(
            system_prompt="system", user_payload={}, response_schema={}
        )


def test_empty_provider_message_content_is_rejected():
    empty = FakeResponse(content={"choices": [{"message": {"content": "   "}}]})
    with pytest.raises(LLMResponseError, match="empty message content"):
        LLMService(settings(), session=FakeSession([empty])).request_json(
            system_prompt="system", user_payload={}, response_schema={}
        )
