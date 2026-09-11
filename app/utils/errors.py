"""Application-level exception types used by the shell and future services."""


class ApplicationError(Exception):
    """Base class for expected, user-safe application failures."""


class ConfigurationError(ApplicationError):
    """Raised when required runtime configuration is invalid."""

