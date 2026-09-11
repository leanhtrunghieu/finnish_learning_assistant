"""Logging setup shared by the Streamlit entry point and future services."""

import logging

from app.utils.errors import ConfigurationError


def configure_logging(level: str = "INFO") -> None:
    """Configure concise console logging for the current application process."""

    normalized_level = level.upper().strip()
    numeric_level = getattr(logging, normalized_level, None)
    if not isinstance(numeric_level, int):
        raise ConfigurationError(f"Unsupported log level: {level!r}.")

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

