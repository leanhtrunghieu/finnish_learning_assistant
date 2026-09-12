import sqlite3
from datetime import datetime, timezone

import pytest

from app.models.grammar import AnalysisStatus, ErrorType, GrammarError, GrammarResult, LanguageMode
from app.services.database_service import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseIntegrityError,
    DatabaseService,
)


def make_error(
    text: str = "menee",
    correction: str = "menen",
    error_type: ErrorType = ErrorType.VERB_CONJUGATION,
) -> GrammarError:
    return GrammarError(
        text=text,
        correction=correction,
        error_type=error_type,
        explanation="The verb must agree with the subject.",
        confidence=0.9,
    )


def make_result(
    sentence: str = "Minä menee kouluun.",
    *,
    errors: tuple[GrammarError, ...] = (make_error(),),
    corrected_sentence: str = "Minä menen kouluun.",
    status: AnalysisStatus = AnalysisStatus.COMPLETE,
) -> GrammarResult:
    return GrammarResult(
        original_sentence=sentence,
        is_correct=not errors,
        corrected_sentence=sentence if not errors else corrected_sentence,
        errors=errors,
        overall_explanation="The sentence was analyzed.",
        learning_tip="Check agreement with the subject.",
        language_mode=LanguageMode.STANDARD,
        analysis_status=status,
        uncertainty_note="The provider was uncertain." if status is AnalysisStatus.UNCERTAIN else None,
    )


def fixed_clock() -> datetime:
    return datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)


def test_initialization_is_idempotent_and_creates_expected_schema(tmp_path):
    database = DatabaseService(tmp_path / "history.db")
    database.initialize()
    database.initialize()

    with sqlite3.connect(database.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"grammar_checks", "grammar_errors"}.issubset(tables)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_correct_check_is_saved_without_error_rows(tmp_path):
    database = DatabaseService(tmp_path / "history.db", clock=fixed_clock)
    result = make_result(errors=())

    check_id = database.save_grammar_result("demo_user", result)

    stored = database.get_grammar_check(check_id, learner_id="demo_user")
    assert stored is not None
    assert stored.is_correct is True
    assert stored.errors == ()
    assert database.get_errors_for_check(check_id) == ()


def test_incorrect_multiple_errors_are_saved_in_order(tmp_path):
    database = DatabaseService(tmp_path / "history.db", clock=fixed_clock)
    errors = (
        make_error(),
        make_error("koira", "koiraa", ErrorType.NOUN_INFLECTION),
        make_error("talo", "talossa", ErrorType.CASE_ERROR),
    )

    check_id = database.save_grammar_result("demo_user", make_result(errors=errors))
    stored = database.get_grammar_check(check_id)

    assert stored is not None
    assert len(stored.errors) == 3
    assert [error.error_index for error in stored.errors] == [0, 1, 2]
    assert [error.error_type for error in stored.errors] == [
        ErrorType.VERB_CONJUGATION,
        ErrorType.NOUN_INFLECTION,
        ErrorType.CASE_ERROR,
    ]


def test_foreign_keys_reject_orphan_error_rows(tmp_path):
    database = DatabaseService(tmp_path / "history.db")
    database.initialize()

    with sqlite3.connect(database.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO grammar_errors
                    (grammar_check_id, error_index, error_type, error_text,
                     correction, explanation, confidence)
                VALUES (999, 0, 'OTHER', 'x', 'y', 'explanation', 0.5)
                """
            )


def test_foreign_key_cascade_deletes_child_errors(tmp_path):
    database = DatabaseService(tmp_path / "history.db", clock=fixed_clock)
    check_id = database.save_grammar_result("demo_user", make_result())

    with sqlite3.connect(database.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM grammar_checks WHERE id = ?", (check_id,))

    assert database.get_grammar_check(check_id) is None
    assert database.get_errors_for_check(check_id) == ()


def test_transaction_rolls_back_check_when_error_insert_fails(tmp_path):
    database = DatabaseService(tmp_path / "history.db", clock=fixed_clock)
    database.initialize()
    with sqlite3.connect(database.database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_error_insert
            BEFORE INSERT ON grammar_errors
            BEGIN
                SELECT RAISE(ABORT, 'forced test failure');
            END
            """
        )

    with pytest.raises(DatabaseIntegrityError):
        database.save_grammar_result("demo_user", make_result())

    assert database.get_recent_checks("demo_user") == ()


def test_history_retrieval_is_learner_scoped_and_newest_first(tmp_path):
    timestamps = iter(
        [
            datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 12, 12, 1, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 12, 12, 2, 0, tzinfo=timezone.utc),
        ]
    )
    database = DatabaseService(tmp_path / "history.db", clock=lambda: next(timestamps))
    first = database.save_grammar_result("demo_user", make_result())
    database.save_grammar_result("other_user", make_result(sentence="Hän menee kotiin."))
    third = database.save_grammar_result("demo_user", make_result(sentence="He menee kotiin."))

    recent = database.get_recent_checks("demo_user", limit=1)
    assert len(recent) == 1
    assert recent[0].id == third
    assert database.get_grammar_check(first, learner_id="other_user") is None
    assert database.get_grammar_check(first, learner_id="demo_user") is not None


def test_uncertain_errors_can_be_retrieved_but_are_filterable(tmp_path):
    database = DatabaseService(tmp_path / "history.db", clock=fixed_clock)
    check_id = database.save_grammar_result(
        "demo_user",
        make_result(status=AnalysisStatus.UNCERTAIN),
    )

    assert len(database.get_learner_errors("demo_user")) == 1
    assert database.get_learner_errors("demo_user", include_uncertain=False) == ()
    assert database.get_errors_for_check(check_id, learner_id="demo_user")


def test_invalid_learner_id_and_limit_are_rejected(tmp_path):
    database = DatabaseService(tmp_path / "history.db")
    with pytest.raises(DatabaseConfigurationError):
        database.save_grammar_result("   ", make_result())
    with pytest.raises(DatabaseConfigurationError, match="surrounding whitespace"):
        database.save_grammar_result(" demo_user ", make_result())
    with pytest.raises(DatabaseConfigurationError):
        database.get_recent_checks("demo_user", limit=0)


def test_missing_parent_directory_is_created_and_corrupt_database_is_reported(tmp_path):
    nested_database = DatabaseService(tmp_path / "missing" / "nested" / "history.db")
    nested_database.initialize()
    assert nested_database.database_path.exists()

    corrupt_path = tmp_path / "corrupt.db"
    corrupt_path.write_bytes(b"this is not a SQLite database")
    with pytest.raises(DatabaseConnectionError, match="database initialization failed"):
        DatabaseService(corrupt_path).initialize()


def test_noncanonical_error_type_is_rejected_before_insertion(tmp_path):
    database = DatabaseService(tmp_path / "history.db")
    error = make_error()
    object.__setattr__(error, "error_type", "NOT_CANONICAL")
    result = make_result(errors=(error,))

    with pytest.raises(DatabaseConfigurationError, match="non-canonical"):
        database.save_grammar_result("demo_user", result)
