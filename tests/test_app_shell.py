"""Smoke tests for the Phase 1 Streamlit application shell."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.config import get_settings
from app.ui.home import APP_DESCRIPTION


APP_ENTRY_POINT = Path(__file__).resolve().parents[1] / "app.py"


def test_home_description_mentions_the_product_purpose() -> None:
    assert "Finnish learners" in APP_DESCRIPTION
    assert "grammar" in APP_DESCRIPTION


def test_streamlit_app_starts_without_optional_api_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    get_settings.cache_clear()

    app = AppTest.from_file(APP_ENTRY_POINT).run()

    assert not app.exception
    assert not app.error
    assert [title.value for title in app.title] == ["Finnish Learning Assistant"]
    get_settings.cache_clear()


def test_streamlit_app_handles_invalid_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    get_settings.cache_clear()

    app = AppTest.from_file(APP_ENTRY_POINT).run()

    assert not app.exception
    assert [error.value for error in app.error] == [
        "The application could not start because its configuration is invalid."
    ]
    get_settings.cache_clear()
