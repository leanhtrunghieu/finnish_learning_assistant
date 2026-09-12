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
    session = FakeSession([FakeResponse(status_code=400)])
    with pytest.raises(LLMProviderError, match="rejected"):
        LLMService(settings(), session=session).request_json(
            system_prompt="system", user_payload={}, response_schema={}
        )
    assert len(session.calls) == 1


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
