"""Environment-backed configuration for the application shell."""

from dataclasses import dataclass
from functools import lru_cache
import os

from dotenv import load_dotenv

from app.utils.errors import ConfigurationError


DEFAULT_APP_TITLE = "Finnish Learning Assistant"
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by the application layers.

    LLM-related fields are configuration only in Phase 1. No API client or
    language-model behavior is implemented yet.
    """

    app_title: str
    environment: str
    log_level: str
    llm_api_key: str | None
    llm_api_base_url: str | None
    llm_model: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        """Load and validate settings from the process environment and .env."""

        load_dotenv()

        app_title = os.getenv("APP_TITLE", DEFAULT_APP_TITLE).strip()
        if not app_title:
            raise ConfigurationError("APP_TITLE must not be empty.")

        environment = os.getenv("APP_ENV", "development").strip().lower()
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in _VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
            raise ConfigurationError(
                f"LOG_LEVEL must be one of: {allowed}."
            )

        return cls(
            app_title=app_title,
            environment=environment or "development",
            log_level=log_level,
            llm_api_key=_optional_env("LLM_API_KEY"),
            llm_api_base_url=_optional_env("LLM_API_BASE_URL"),
            llm_model=_optional_env("LLM_MODEL"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached settings instance for the current process."""

    return Settings.from_environment()

