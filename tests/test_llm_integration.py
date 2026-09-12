"""Opt-in live provider smoke tests; normal CI never requires credentials."""

import os

import pytest

from app.models.grammar import LanguageMode
from app.services.grammar_service import GrammarService
from app.services.llm_service import LLMService


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="set RUN_LIVE_LLM_TESTS=1 with configured credentials to run live API checks",
)


def test_live_correct_sentence_does_not_invent_error():
    result = GrammarService(LLMService()).check_sentence("Minä menen kouluun.")
    assert result.original_sentence == "Minä menen kouluun."
    assert result.is_correct is True
    assert result.errors == ()


def test_live_obvious_error_returns_supported_correction():
    result = GrammarService(LLMService()).check_sentence("Minä menee kouluun.")
    assert result.is_correct is False
    assert result.errors
    assert any(error.error_type.value == "VERB_CONJUGATION" for error in result.errors)
    assert result.corrected_sentence


def test_live_colloquial_mode_is_available():
    result = GrammarService(LLMService()).check_sentence(
        "Mä meen kotiin.", language_mode=LanguageMode.COLLOQUIAL_TOLERANT
    )
    assert result.language_mode is LanguageMode.COLLOQUIAL_TOLERANT
