"""Learner weakness aggregation derived from persisted grammar errors."""

from __future__ import annotations

from app.models.learner import LearnerProfile, LearnerWeakness
from app.services.database_service import DatabaseService


class ProfileService:
    """Calculate deterministic learner weaknesses from actual database rows."""

    def __init__(self, database_service: DatabaseService) -> None:
        self.database_service = database_service

    def get_profile(self, learner_id: str) -> LearnerProfile:
        total_checks = self.database_service.count_grammar_checks(learner_id)
        statistics = self.database_service.get_error_statistics(
            learner_id,
            include_uncertain=False,
        )
        total_errors = sum(count for _, count, _ in statistics)
        if total_errors == 0:
            return LearnerProfile(
                learner_id=learner_id,
                total_checks=total_checks,
                total_errors=0,
                weaknesses=(),
            )

        weaknesses = tuple(
            LearnerWeakness(
                error_type=error_type,
                count=count,
                percentage=round(count / total_errors * 100, 2),
                last_seen=last_seen,
            )
            for error_type, count, last_seen in sorted(
                statistics,
                key=lambda item: (-item[1], item[0].value),
            )
        )
        return LearnerProfile(
            learner_id=learner_id,
            total_checks=total_checks,
            total_errors=total_errors,
            weaknesses=weaknesses,
        )
