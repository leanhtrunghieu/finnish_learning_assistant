"""Tests for Phase 1 configuration management."""

import pytest

from app.config import DEFAULT_APP_TITLE, get_settings
from app.utils.errors import ConfigurationError


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_TITLE", "Test Finnish Assistant")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_title == "Test Finnish Assistant"
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.llm_api_key is None

    get_settings.cache_clear()


def test_default_title_is_available() -> None:
    assert DEFAULT_APP_TITLE == "Finnish Learning Assistant"


def test_invalid_log_level_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError):
        get_settings()

    get_settings.cache_clear()

