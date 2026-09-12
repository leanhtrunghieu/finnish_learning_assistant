"""Cached construction of stable application services for the Streamlit UI."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.services.database_service import DatabaseService
from app.services.exercise_service import ExerciseService
from app.services.grammar_service import GrammarService
from app.services.llm_service import LLMService
from app.services.profile_service import ProfileService
from app.services.vocabulary_service import VocabularyService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VOCABULARY_INDEX_PATH = PROJECT_ROOT / "data" / "vocabulary" / "vocabulary_index_v1.jsonl"


@st.cache_resource
def get_database_service() -> DatabaseService:
    """Return one initialized local database service per app process."""

    database = DatabaseService()
    database.initialize()
    return database


@st.cache_resource
def get_profile_service() -> ProfileService:
    """Return a profile service backed by the cached database service."""

    return ProfileService(get_database_service())


@st.cache_resource
def get_llm_service() -> LLMService:
    """Return the provider-neutral LLM service.

    Instantiation is intentionally safe without credentials; a useful
    configuration error is raised only if an LLM-backed action is requested.
    """

    return LLMService()


@st.cache_resource
def get_grammar_service() -> GrammarService:
    """Return the grammar service using the shared LLM transport."""

    return GrammarService(get_llm_service())


@st.cache_resource
def get_vocabulary_service() -> VocabularyService:
    """Load the static vocabulary index once per app process."""

    return VocabularyService(VOCABULARY_INDEX_PATH)


@st.cache_resource
def get_exercise_service() -> ExerciseService:
    """Return the profile-driven exercise service."""

    return ExerciseService(get_profile_service(), get_llm_service())
