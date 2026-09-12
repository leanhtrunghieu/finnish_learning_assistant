from datetime import datetime, timezone

from app.models.grammar import ErrorType, GrammarError, GrammarResult, AnalysisStatus, LanguageMode
from app.services.database_service import DatabaseService
from app.services.profile_service import ProfileService


def result_for(
    sentence: str,
    errors: tuple[GrammarError, ...],
    *,
    status: AnalysisStatus = AnalysisStatus.COMPLETE,
) -> GrammarResult:
    return GrammarResult(
        original_sentence=sentence,
        is_correct=not errors,
        corrected_sentence=sentence if not errors else sentence + " korjattu",
        errors=errors,
        overall_explanation="Analysis.",
        learning_tip="Review the pattern.",
        language_mode=LanguageMode.STANDARD,
        analysis_status=status,
        uncertainty_note="Uncertain context." if status is AnalysisStatus.UNCERTAIN else None,
    )


def error(error_type: ErrorType, text: str = "virhe", correction: str = "korjaus") -> GrammarError:
    return GrammarError(
        text=text,
        correction=correction,
        error_type=error_type,
        explanation="Learner-facing explanation.",
        confidence=0.7,
    )


def clock() -> datetime:
    return datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def test_zero_error_profile_is_valid(tmp_path):
    database = DatabaseService(tmp_path / "profile.db", clock=clock)
    database.save_grammar_result(
        "demo_user",
        result_for("Minä menen kouluun.", ()),
    )

    profile = ProfileService(database).get_profile("demo_user")

    assert profile.total_checks == 1
    assert profile.total_errors == 0
    assert profile.weaknesses == ()
    assert profile.primary_weakness is None


def test_profile_counts_percentages_and_tie_order_are_deterministic(tmp_path):
    database = DatabaseService(tmp_path / "profile.db", clock=clock)
    database.save_grammar_result(
        "demo_user",
        result_for(
            "Minä menee kotiin.",
            (error(ErrorType.VERB_CONJUGATION, "menee", "menen"),
             error(ErrorType.CASE_ERROR, "kotiin", "koti")),
        ),
    )
    database.save_grammar_result(
        "demo_user",
        result_for(
            "Hän käy koulu.",
            (error(ErrorType.CASE_ERROR, "koulu", "koulussa"),),
        ),
    )
    database.save_grammar_result(
        "demo_user",
        result_for(
            "He menee koti.",
            (error(ErrorType.VERB_CONJUGATION, "menee", "menevät"),),
        ),
    )

    profile = ProfileService(database).get_profile("demo_user")

    assert profile.total_checks == 3
    assert profile.total_errors == 4
    assert [weakness.error_type for weakness in profile.weaknesses] == [
        ErrorType.CASE_ERROR,
        ErrorType.VERB_CONJUGATION,
    ]
    assert [weakness.count for weakness in profile.weaknesses] == [2, 2]
    assert [weakness.percentage for weakness in profile.weaknesses] == [50.0, 50.0]
    assert profile.primary_weakness is ErrorType.CASE_ERROR
    assert sum(weakness.percentage for weakness in profile.weaknesses) == 100.0


def test_uncertain_errors_are_not_counted_but_correct_checks_are_history(tmp_path):
    database = DatabaseService(tmp_path / "profile.db", clock=clock)
    database.save_grammar_result(
        "demo_user",
        result_for("Minä menee kotiin.", (error(ErrorType.VERB_CONJUGATION, "menee", "menen"),)),
    )
    database.save_grammar_result(
        "demo_user",
        result_for(
            "Ehkä hän palaa.",
            (error(ErrorType.CASE_ERROR, "palaa", "palaa?"),),
            status=AnalysisStatus.UNCERTAIN,
        ),
    )
    database.save_grammar_result("demo_user", result_for("Minä menen kotiin.", ()))

    profile = ProfileService(database).get_profile("demo_user")

    assert profile.total_checks == 3
    assert profile.total_errors == 1
    assert [weakness.error_type for weakness in profile.weaknesses] == [ErrorType.VERB_CONJUGATION]


def test_profiles_are_isolated_by_learner_id(tmp_path):
    database = DatabaseService(tmp_path / "profile.db", clock=clock)
    database.save_grammar_result(
        "demo_user",
        result_for("Minä menee.", (error(ErrorType.VERB_CONJUGATION, "menee", "menen"),)),
    )
    database.save_grammar_result(
        "other_user",
        result_for("Hän käy koulu.", (error(ErrorType.CASE_ERROR, "koulu", "koulussa"),)),
    )

    demo = ProfileService(database).get_profile("demo_user")
    other = ProfileService(database).get_profile("other_user")

    assert demo.total_errors == 1
    assert demo.primary_weakness is ErrorType.VERB_CONJUGATION
    assert other.total_errors == 1
    assert other.primary_weakness is ErrorType.CASE_ERROR
