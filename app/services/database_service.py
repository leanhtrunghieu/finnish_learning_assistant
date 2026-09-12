"""SQLite persistence for grammar checks and learner error history."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from app.models.grammar import AnalysisStatus, ErrorType, GrammarError, GrammarResult, LanguageMode
from app.models.learner import StoredGrammarCheck, StoredGrammarError


DATABASE_SCHEMA_VERSION = 1
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "database" / "finnish_learning_assistant.db"
DEFAULT_LEARNER_ID = "demo_user"
MAX_LEARNER_ID_CHARS = 64
MAX_RETRIEVAL_LIMIT = 1_000

CANONICAL_ERROR_TYPES = tuple(error_type.value for error_type in ErrorType)
_ERROR_TYPE_SQL = ", ".join(f"'{value}'" for value in CANONICAL_ERROR_TYPES)


class DatabaseError(RuntimeError):
    """Base class for expected learner-history persistence failures."""


class DatabaseConfigurationError(DatabaseError):
    """Raised for invalid database-service inputs or unsupported schema versions."""


class DatabaseConnectionError(DatabaseError):
    """Raised when the database cannot be opened or initialized."""


class DatabaseIntegrityError(DatabaseError):
    """Raised when a transaction violates a database constraint."""


SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS grammar_checks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id          TEXT NOT NULL,
    schema_version      TEXT NOT NULL,
    original_sentence   TEXT NOT NULL,
    corrected_sentence  TEXT NOT NULL,
    is_correct          INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    overall_explanation TEXT NOT NULL,
    learning_tip        TEXT NOT NULL,
    language_mode       TEXT NOT NULL,
    analysis_status     TEXT NOT NULL,
    uncertainty_note    TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grammar_errors (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    grammar_check_id   INTEGER NOT NULL,
    error_index        INTEGER NOT NULL,
    error_type         TEXT NOT NULL CHECK (error_type IN ({_ERROR_TYPE_SQL})),
    error_text         TEXT NOT NULL,
    correction         TEXT NOT NULL,
    explanation        TEXT NOT NULL,
    confidence         REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    FOREIGN KEY (grammar_check_id) REFERENCES grammar_checks(id) ON DELETE CASCADE,
    UNIQUE (grammar_check_id, error_index)
);

CREATE INDEX IF NOT EXISTS idx_grammar_checks_learner_created
    ON grammar_checks (learner_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_grammar_errors_check_index
    ON grammar_errors (grammar_check_id, error_index);
CREATE INDEX IF NOT EXISTS idx_grammar_errors_type
    ON grammar_errors (error_type);
"""


class DatabaseService:
    """Small repository-style service around the local SQLite database."""

    def __init__(
        self,
        database_path: str | Path = DEFAULT_DATABASE_PATH,
        *,
        timeout_seconds: float = 5.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.database_path = Path(database_path)
        self.timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def initialize(self) -> None:
        """Create the v1 schema without dropping or replacing existing data."""
        connection = self._connect()
        try:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version not in (0, DATABASE_SCHEMA_VERSION):
                raise DatabaseConfigurationError(
                    f"unsupported database schema version: {current_version}"
                )
            connection.executescript(SCHEMA_SQL)
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
        except DatabaseError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseConnectionError("database initialization failed") from exc
        finally:
            connection.close()

    def save_grammar_result(self, learner_id: str, result: GrammarResult) -> int:
        """Persist one result and all of its errors in one transaction."""
        self._validate_learner_id(learner_id)
        self._validate_result(result)
        self.initialize()
        created_at = self._utc_timestamp()
        connection = self._open_connection()
        try:
            connection.execute("BEGIN")
            cursor = connection.execute(
                """
                INSERT INTO grammar_checks (
                    learner_id, schema_version, original_sentence, corrected_sentence,
                    is_correct, overall_explanation, learning_tip, language_mode,
                    analysis_status, uncertainty_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    learner_id,
                    result.schema_version,
                    result.original_sentence,
                    result.corrected_sentence,
                    int(result.is_correct),
                    result.overall_explanation,
                    result.learning_tip,
                    result.language_mode.value,
                    result.analysis_status.value,
                    result.uncertainty_note,
                    created_at,
                ),
            )
            check_id = int(cursor.lastrowid)
            for error_index, error in enumerate(result.errors):
                connection.execute(
                    """
                    INSERT INTO grammar_errors (
                        grammar_check_id, error_index, error_type, error_text,
                        correction, explanation, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        check_id,
                        error_index,
                        error.error_type.value,
                        error.text,
                        error.correction,
                        error.explanation,
                        error.confidence,
                    ),
                )
            connection.commit()
            return check_id
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise DatabaseIntegrityError("grammar result transaction violated a database constraint") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise DatabaseError("grammar result transaction failed") from exc
        finally:
            connection.close()

    def get_grammar_check(self, check_id: int, *, learner_id: str | None = None) -> StoredGrammarCheck | None:
        """Return one stored check, optionally restricted to a learner."""
        self._validate_positive_id(check_id, "check_id")
        if learner_id is not None:
            self._validate_learner_id(learner_id)
        self.initialize()
        connection = self._open_connection()
        try:
            query = "SELECT * FROM grammar_checks WHERE id = ?"
            parameters: list[object] = [check_id]
            if learner_id is not None:
                query += " AND learner_id = ?"
                parameters.append(learner_id)
            row = connection.execute(query, parameters).fetchone()
            if row is None:
                return None
            errors = self._fetch_errors(connection, check_id)
            return self._check_from_row(row, errors)
        except sqlite3.Error as exc:
            raise DatabaseError("could not retrieve grammar check") from exc
        finally:
            connection.close()

    def get_recent_checks(self, learner_id: str, *, limit: int = 20) -> tuple[StoredGrammarCheck, ...]:
        """Return recent checks in newest-first order."""
        self._validate_learner_id(learner_id)
        self._validate_limit(limit)
        self.initialize()
        connection = self._open_connection()
        try:
            rows = connection.execute(
                """
                SELECT * FROM grammar_checks
                WHERE learner_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (learner_id, limit),
            ).fetchall()
            return tuple(self._check_from_row(row, self._fetch_errors(connection, int(row["id"]))) for row in rows)
        except sqlite3.Error as exc:
            raise DatabaseError("could not retrieve recent grammar checks") from exc
        finally:
            connection.close()

    def get_errors_for_check(
        self,
        check_id: int,
        *,
        learner_id: str | None = None,
    ) -> tuple[StoredGrammarError, ...]:
        """Return errors for one check, optionally enforcing learner ownership."""
        self._validate_positive_id(check_id, "check_id")
        if learner_id is not None:
            self._validate_learner_id(learner_id)
        self.initialize()
        connection = self._open_connection()
        try:
            if learner_id is not None:
                exists = connection.execute(
                    "SELECT 1 FROM grammar_checks WHERE id = ? AND learner_id = ?",
                    (check_id, learner_id),
                ).fetchone()
                if exists is None:
                    return ()
            return self._fetch_errors(connection, check_id)
        except sqlite3.Error as exc:
            raise DatabaseError("could not retrieve grammar errors") from exc
        finally:
            connection.close()

    def get_learner_errors(
        self,
        learner_id: str,
        *,
        limit: int | None = None,
        include_uncertain: bool = True,
    ) -> tuple[StoredGrammarError, ...]:
        """Return persisted errors for a learner in newest-check-first order."""
        self._validate_learner_id(learner_id)
        if limit is not None:
            self._validate_limit(limit)
        self.initialize()
        connection = self._open_connection()
        try:
            query = """
                SELECT ge.*
                FROM grammar_errors AS ge
                JOIN grammar_checks AS gc ON gc.id = ge.grammar_check_id
                WHERE gc.learner_id = ?
            """
            parameters: list[object] = [learner_id]
            if not include_uncertain:
                query += " AND gc.analysis_status = ?"
                parameters.append(AnalysisStatus.COMPLETE.value)
            query += " ORDER BY gc.created_at DESC, gc.id DESC, ge.error_index ASC"
            if limit is not None:
                query += " LIMIT ?"
                parameters.append(limit)
            rows = connection.execute(query, parameters).fetchall()
            return tuple(self._error_from_row(row) for row in rows)
        except sqlite3.Error as exc:
            raise DatabaseError("could not retrieve learner errors") from exc
        finally:
            connection.close()

    def count_grammar_checks(self, learner_id: str) -> int:
        self._validate_learner_id(learner_id)
        self.initialize()
        connection = self._open_connection()
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM grammar_checks WHERE learner_id = ?", (learner_id,)
                ).fetchone()[0]
            )
        except sqlite3.Error as exc:
            raise DatabaseError("could not count grammar checks") from exc
        finally:
            connection.close()

    def get_error_statistics(
        self,
        learner_id: str,
        *,
        include_uncertain: bool = False,
    ) -> tuple[tuple[ErrorType, int, str | None], ...]:
        """Return (category, count, last_seen) aggregates for profile calculation."""
        self._validate_learner_id(learner_id)
        self.initialize()
        connection = self._open_connection()
        try:
            query = """
                SELECT ge.error_type, COUNT(*) AS error_count, MAX(gc.created_at) AS last_seen
                FROM grammar_errors AS ge
                JOIN grammar_checks AS gc ON gc.id = ge.grammar_check_id
                WHERE gc.learner_id = ?
            """
            parameters: list[object] = [learner_id]
            if not include_uncertain:
                query += " AND gc.analysis_status = ?"
                parameters.append(AnalysisStatus.COMPLETE.value)
            query += " GROUP BY ge.error_type"
            rows = connection.execute(query, parameters).fetchall()
            return tuple((ErrorType(row["error_type"]), int(row["error_count"]), row["last_seen"]) for row in rows)
        except (sqlite3.Error, ValueError) as exc:
            raise DatabaseError("could not aggregate learner errors") from exc
        finally:
            connection.close()

    def _open_connection(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                str(self.database_path), timeout=self.timeout_seconds, detect_types=sqlite3.PARSE_DECLTYPES
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise DatabaseConnectionError("could not open SQLite database") from exc

    def _connect(self) -> sqlite3.Connection:
        if str(self.database_path) == ":memory:":
            raise DatabaseConfigurationError("':memory:' is not supported because service operations use separate connections")
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DatabaseConnectionError("could not create database directory") from exc
        return self._open_connection()

    @staticmethod
    def _fetch_errors(connection: sqlite3.Connection, check_id: int) -> tuple[StoredGrammarError, ...]:
        rows = connection.execute(
            "SELECT * FROM grammar_errors WHERE grammar_check_id = ? ORDER BY error_index ASC",
            (check_id,),
        ).fetchall()
        return tuple(DatabaseService._error_from_row(row) for row in rows)

    @staticmethod
    def _error_from_row(row: sqlite3.Row) -> StoredGrammarError:
        try:
            error_type = ErrorType(row["error_type"])
        except ValueError as exc:
            raise DatabaseError("database contains an unknown canonical error type") from exc
        return StoredGrammarError(
            id=int(row["id"]),
            grammar_check_id=int(row["grammar_check_id"]),
            error_index=int(row["error_index"]),
            error_type=error_type,
            error_text=str(row["error_text"]),
            correction=str(row["correction"]),
            explanation=str(row["explanation"]),
            confidence=float(row["confidence"]),
        )

    @staticmethod
    def _check_from_row(row: sqlite3.Row, errors: Iterable[StoredGrammarError]) -> StoredGrammarCheck:
        try:
            language_mode = LanguageMode(row["language_mode"])
            analysis_status = AnalysisStatus(row["analysis_status"])
        except ValueError as exc:
            raise DatabaseError("database contains an unsupported grammar result enum") from exc
        return StoredGrammarCheck(
            id=int(row["id"]),
            learner_id=str(row["learner_id"]),
            schema_version=str(row["schema_version"]),
            original_sentence=str(row["original_sentence"]),
            corrected_sentence=str(row["corrected_sentence"]),
            is_correct=bool(row["is_correct"]),
            overall_explanation=str(row["overall_explanation"]),
            learning_tip=str(row["learning_tip"]),
            language_mode=language_mode,
            analysis_status=analysis_status,
            uncertainty_note=row["uncertainty_note"],
            created_at=str(row["created_at"]),
            errors=tuple(errors),
        )

    def _utc_timestamp(self) -> str:
        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _validate_learner_id(learner_id: str) -> None:
        if not isinstance(learner_id, str) or not learner_id.strip():
            raise DatabaseConfigurationError("learner_id must be a non-empty string")
        if learner_id != learner_id.strip():
            raise DatabaseConfigurationError("learner_id must not contain surrounding whitespace")
        if len(learner_id) > MAX_LEARNER_ID_CHARS:
            raise DatabaseConfigurationError(
                f"learner_id exceeds the {MAX_LEARNER_ID_CHARS}-character limit"
            )

    @staticmethod
    def _validate_positive_id(value: int, field: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise DatabaseConfigurationError(f"{field} must be a positive integer")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RETRIEVAL_LIMIT:
            raise DatabaseConfigurationError(
                f"limit must be an integer between 1 and {MAX_RETRIEVAL_LIMIT}"
            )

    @staticmethod
    def _validate_result(result: GrammarResult) -> None:
        if not isinstance(result, GrammarResult):
            raise DatabaseConfigurationError("result must be a validated GrammarResult")
        for error in result.errors:
            if not isinstance(error, GrammarError) or not isinstance(error.error_type, ErrorType):
                raise DatabaseConfigurationError("result contains a non-canonical grammar error")
