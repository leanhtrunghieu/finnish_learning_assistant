"""Profile-driven Finnish exercise generation above the shared LLM transport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.models.exercise import (
    Exercise,
    ExerciseAttemptResult,
    ExerciseDifficulty,
    ExerciseSelectionSource,
    ExerciseType,
    ExerciseValidationError,
    SUPPORTED_GENERATION_ERROR_TYPES,
    exercise_response_schema,
    normalize_answer,
)
from app.models.grammar import ErrorType
from app.models.learner import LearnerProfile
from app.services.llm_service import (
    LLMAuthenticationError,
    LLMClient,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServiceError,
    LLMTimeoutError,
)
from app.services.profile_service import ProfileService


DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "exercise_generator_prompt.txt"


class ExerciseServiceError(RuntimeError):
    """Expected exercise-service failure safe for a future UI."""


class ExerciseTargetUnavailableError(ExerciseServiceError):
    """Raised when no supported weakness is available for automatic practice."""


class ExerciseService:
    """Select a structured weakness and generate one validated exercise."""

    def __init__(
        self,
        profile_service: ProfileService,
        llm_client: LLMClient,
        *,
        prompt_path: Path = DEFAULT_PROMPT_PATH,
        allow_repair_retry: bool = True,
    ) -> None:
        self.profile_service = profile_service
        self.llm_client = llm_client
        self.prompt_path = prompt_path
        self.allow_repair_retry = allow_repair_retry

    @staticmethod
    def select_target(
        profile: LearnerProfile,
        explicit_error_type: ErrorType | str | None = None,
    ) -> tuple[ErrorType, ExerciseSelectionSource]:
        """Select the highest ranked supported weakness with deterministic ties."""

        if not isinstance(profile, LearnerProfile):
            raise ExerciseTargetUnavailableError("a valid learner profile is required")
        if explicit_error_type is not None:
            error_type = ExerciseService._coerce_error_type(explicit_error_type)
            if error_type not in SUPPORTED_GENERATION_ERROR_TYPES:
                raise ExerciseTargetUnavailableError(
                    f"{error_type.value} is not supported for automatic exercises"
                )
            return error_type, ExerciseSelectionSource.USER_SELECTED
        for weakness in sorted(
            profile.weaknesses,
            key=lambda item: (-item.count, item.error_type.value),
        ):
            if weakness.error_type in SUPPORTED_GENERATION_ERROR_TYPES:
                return weakness.error_type, ExerciseSelectionSource.LEARNER_PROFILE
        raise ExerciseTargetUnavailableError(
            "no supported grammar weakness is available; choose an explicit practice topic"
        )

    def generate_for_learner(
        self,
        learner_id: str,
        *,
        difficulty: ExerciseDifficulty = ExerciseDifficulty.BASIC,
        error_type: ErrorType | str | None = None,
    ) -> Exercise:
        """Load the actual profile, then generate a targeted exercise."""

        profile = self.profile_service.get_profile(learner_id)
        return self.generate_for_profile(profile, difficulty=difficulty, error_type=error_type)

    def generate_for_profile(
        self,
        profile: LearnerProfile,
        *,
        difficulty: ExerciseDifficulty = ExerciseDifficulty.BASIC,
        error_type: ErrorType | str | None = None,
    ) -> Exercise:
        difficulty = self._coerce_difficulty(difficulty)
        target, selection_source = self.select_target(profile, error_type)
        metadata = self._selection_metadata(profile, target)
        try:
            prompt = self._load_prompt(target, difficulty)
        except OSError as exc:
            raise ExerciseServiceError("exercise prompt could not be loaded") from exc
        payload = {
            "target_error_type": target.value,
            "exercise_type": ExerciseType.MULTIPLE_CHOICE.value,
            "difficulty": difficulty.value,
        }
        try:
            raw = self._request(prompt, payload)
            return Exercise.from_provider_dict(
                raw,
                expected_error_type=target,
                expected_exercise_type=ExerciseType.MULTIPLE_CHOICE,
                expected_difficulty=difficulty,
                selection_source=selection_source,
                metadata=metadata,
            )
        except (ExerciseValidationError, LLMResponseError) as first_error:
            if not self.allow_repair_retry:
                raise ExerciseServiceError(self._safe_message(first_error)) from first_error
            repair_prompt = (
                prompt
                + "\nYour previous response was invalid. Return one JSON object matching the schema exactly. "
                + "Do not add commentary, markdown fences, an ID, or unsupported fields."
            )
            try:
                repaired = self._request(repair_prompt, payload)
                return Exercise.from_provider_dict(
                    repaired,
                    expected_error_type=target,
                    expected_exercise_type=ExerciseType.MULTIPLE_CHOICE,
                    expected_difficulty=difficulty,
                    selection_source=selection_source,
                    metadata=metadata,
                )
            except (ExerciseValidationError, LLMServiceError) as second_error:
                raise ExerciseServiceError(self._safe_message(second_error)) from second_error
        except LLMServiceError as first_error:
            raise ExerciseServiceError(self._safe_message(first_error)) from first_error

    def check_answer(self, exercise: Exercise, user_answer: str | int) -> ExerciseAttemptResult:
        """Check a multiple-choice answer without another LLM call."""

        if not isinstance(exercise, Exercise):
            raise ExerciseServiceError("a validated Exercise is required")
        try:
            resolved = exercise.answer_for(user_answer)
            is_correct = normalize_answer(resolved) == normalize_answer(exercise.correct_answer)
            stored_answer = user_answer if isinstance(user_answer, str) else str(user_answer)
            return ExerciseAttemptResult(
                exercise_id=exercise.exercise_id,
                user_answer=stored_answer.strip(),
                correct_answer=exercise.correct_answer,
                is_correct=is_correct,
                explanation=exercise.explanation,
            )
        except ExerciseValidationError as exc:
            raise ExerciseServiceError("answer must be an option label or Finnish option text") from exc

    def _request(self, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self.llm_client.request_json(
            system_prompt=prompt,
            user_payload=payload,
            response_schema=exercise_response_schema(),
        )
        if not isinstance(raw, Mapping):
            raise LLMResponseError("exercise provider response must be a JSON object")
        return dict(raw)

    def _load_prompt(self, target: ErrorType, difficulty: ExerciseDifficulty) -> str:
        template = self.prompt_path.read_text(encoding="utf-8")
        schema = json.dumps(exercise_response_schema(), ensure_ascii=False, indent=2)
        return (
            template.replace("{{ERROR_TYPE}}", target.value)
            .replace("{{EXERCISE_TYPE}}", ExerciseType.MULTIPLE_CHOICE.value)
            .replace("{{DIFFICULTY}}", difficulty.value)
            .replace("{{RESPONSE_SCHEMA}}", schema)
        )

    @staticmethod
    def _selection_metadata(profile: LearnerProfile, target: ErrorType) -> dict[str, Any]:
        for weakness in profile.weaknesses:
            if weakness.error_type is target:
                return {
                    "weakness_count": weakness.count,
                    "weakness_percentage": weakness.percentage,
                }
        return {"weakness_count": 0, "weakness_percentage": 0.0}

    @staticmethod
    def _coerce_error_type(value: ErrorType | str) -> ErrorType:
        if isinstance(value, ErrorType):
            return value
        if isinstance(value, str):
            try:
                return ErrorType(value)
            except ValueError as exc:
                raise ExerciseTargetUnavailableError("unknown grammar error type") from exc
        raise ExerciseTargetUnavailableError("error_type must be a canonical ErrorType")

    @staticmethod
    def _coerce_difficulty(value: ExerciseDifficulty | str) -> ExerciseDifficulty:
        if isinstance(value, ExerciseDifficulty):
            return value
        if isinstance(value, str):
            try:
                return ExerciseDifficulty(value)
            except ValueError as exc:
                raise ExerciseServiceError("difficulty must be BASIC") from exc
        raise ExerciseServiceError("difficulty must be an ExerciseDifficulty")

    @staticmethod
    def _safe_message(error: Exception) -> str:
        if isinstance(error, ExerciseValidationError):
            return "The exercise provider returned an exercise that failed schema validation."
        if isinstance(error, LLMConfigurationError):
            return "The exercise service is not configured. Set LLM_API_KEY, LLM_API_BASE_URL, and LLM_MODEL."
        if isinstance(error, LLMAuthenticationError):
            return "The exercise provider rejected authentication. Check the configured API key."
        if isinstance(error, LLMRateLimitError):
            return "The exercise provider is rate-limiting requests. Please try again later."
        if isinstance(error, LLMTimeoutError):
            return "The exercise provider timed out. Please try again later."
        return "The exercise provider is temporarily unavailable or returned an invalid response."


def generate_for_learner(
    learner_id: str,
    *,
    difficulty: ExerciseDifficulty = ExerciseDifficulty.BASIC,
    error_type: ErrorType | str | None = None,
) -> Exercise:
    """Convenience API for future callers; configuration is loaded from the environment."""

    from app.services.llm_service import LLMService
    from app.services.database_service import DatabaseService

    database = DatabaseService()
    database.initialize()
    service = ExerciseService(ProfileService(database), LLMService())
    return service.generate_for_learner(learner_id, difficulty=difficulty, error_type=error_type)
