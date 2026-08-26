import logging
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError
from sqlalchemy.orm import Session

from academic_agents.assessment import AssessmentAgentError
from academic_agents.planning import PlanningAgentError
from academic_agents.runtime import AcademicRuntimeConfigurationError
from academic_retrieval.artifacts import CourseArtifactError
from academic_retrieval.service import AcademicRetrievalError
from assessment.question_bank import QuestionBankError
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from database.models import UserModel
from planning.learning_map import LearningMapError
from schemas.agents import AcademicAssistantRequest, AcademicAssistantResponse
from schemas.assessment import (
    AssessmentStartRequest,
    AssessmentStartResponse,
    AssessmentSubmitResponse,
    CourseMasteryResponse,
)
from schemas.automation import LearningEventListResponse
from schemas.planning import (
    LearningPlanApprovalResponse,
    LearningPlanCreateRequest,
    LearningPlanResponse,
)
from services.academic_agent_service import (
    AcademicAgentLimitError,
    consume_academic_agent_budget,
    consume_academic_assessment_limit,
    consume_academic_planning_limit,
)
from services.assessment_service import (
    AcademicAssessmentService,
    AssessmentConflictError,
    AssessmentNotFoundError,
    AssessmentVerificationError,
)
from services.learning_event_service import LearningEventService
from services.planning_service import (
    AcademicPlanningService,
    PlanningConflictError,
    PlanningConstraintError,
    PlanningNotFoundError,
    PlanningRuntimeError,
)


logger = logging.getLogger(__name__)
T = TypeVar("T")


class AcademicMcpToolError(RuntimeError):
    """Safe error that may be returned to an MCP host/model."""


_PUBLIC_DOMAIN_ERRORS = (
    AssessmentAgentError,
    AssessmentConflictError,
    AssessmentNotFoundError,
    PlanningAgentError,
    PlanningConflictError,
    PlanningConstraintError,
    PlanningNotFoundError,
)
_DEPENDENCY_ERRORS = (
    AcademicRuntimeConfigurationError,
    AcademicRetrievalError,
    CourseArtifactError,
    LearningMapError,
    PlanningRuntimeError,
    QuestionBankError,
)


class AcademicMcpToolAdapter:
    """Reuse application services behind a user-bound MCP boundary."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        runtime,
        *,
        user_id: int,
    ) -> None:
        if user_id <= 0:
            raise ValueError("user_id phải là số nguyên dương.")
        self.session_factory = session_factory
        self.runtime = runtime
        self.user_id = user_id

    def _require_bound_user(self, db: Session) -> None:
        user = db.query(UserModel).filter(UserModel.id == self.user_id).first()
        if user is None:
            raise AcademicMcpToolError(
                "Người dùng được khóa cho MCP server không tồn tại."
            )

    @staticmethod
    def _validate_course_scope(
        course_id: str,
        course_version: str,
    ) -> tuple[str, str]:
        normalized_id = course_id.strip().lower()
        normalized_version = course_version.strip()
        if not COURSE_ID_PATTERN.fullmatch(normalized_id):
            raise AcademicMcpToolError("course_id không hợp lệ.")
        if not VERSION_PATTERN.fullmatch(normalized_version):
            raise AcademicMcpToolError("course_version không hợp lệ.")
        return normalized_id, normalized_version

    @staticmethod
    def _translate_error(exc: Exception) -> AcademicMcpToolError:
        if isinstance(exc, AcademicMcpToolError):
            return exc
        if isinstance(exc, AcademicAgentLimitError):
            return AcademicMcpToolError(
                "Đã đạt giới hạn thao tác; thử lại sau "
                f"{exc.retry_after_seconds} giây."
            )
        if isinstance(exc, ValidationError):
            return AcademicMcpToolError("Dữ liệu đầu vào của tool không hợp lệ.")
        if isinstance(exc, _PUBLIC_DOMAIN_ERRORS):
            return AcademicMcpToolError(str(exc))
        if isinstance(exc, _DEPENDENCY_ERRORS):
            return AcademicMcpToolError(
                "Dữ liệu hoặc runtime của môn học chưa sẵn sàng."
            )
        if isinstance(exc, (AssessmentVerificationError,)):
            return AcademicMcpToolError(
                "Verification Agent đã chặn kết quả assessment không hợp lệ."
            )
        return AcademicMcpToolError(
            "MCP tool chưa thể hoàn thành yêu cầu."
        )

    def _run_db(
        self,
        operation: str,
        action: Callable[[Session], T],
    ) -> T:
        db = self.session_factory()
        try:
            self._require_bound_user(db)
            return action(db)
        except AcademicMcpToolError:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            translated = self._translate_error(exc)
            if isinstance(
                exc,
                (
                    AcademicAgentLimitError,
                    ValidationError,
                    *_PUBLIC_DOMAIN_ERRORS,
                    *_DEPENDENCY_ERRORS,
                    AssessmentVerificationError,
                ),
            ):
                logger.warning(
                    "Academic MCP tool failed.",
                    extra={
                        "operation": operation,
                        "error_type": type(exc).__name__,
                    },
                )
            else:
                logger.exception(
                    "Unexpected academic MCP tool failure.",
                    extra={"operation": operation},
                )
            raise translated from exc
        finally:
            db.close()

    def validate_identity(self) -> None:
        self._run_db("validate_identity", lambda _db: None)

    def ask_course(
        self,
        request: AcademicAssistantRequest,
    ) -> AcademicAssistantResponse:
        self._run_db(
            "ask_course_budget",
            lambda db: consume_academic_agent_budget(
                db,
                user_id=self.user_id,
            ),
        )
        try:
            return self.runtime.ask(request)
        except Exception as exc:
            translated = self._translate_error(exc)
            logger.warning(
                "Academic MCP knowledge workflow failed.",
                extra={
                    "operation": "ask_course",
                    "course_id": request.course_id,
                    "course_version": request.course_version,
                    "error_type": type(exc).__name__,
                },
            )
            raise translated from exc

    def start_assessment(
        self,
        request: AssessmentStartRequest,
    ) -> AssessmentStartResponse:
        def action(db: Session) -> AssessmentStartResponse:
            consume_academic_assessment_limit(db, user_id=self.user_id)
            return AcademicAssessmentService(db, self.runtime).start(
                request,
                user_id=self.user_id,
            )

        return self._run_db("start_assessment", action)

    def submit_assessment(
        self,
        attempt_id: str,
        *,
        selected_option_id: str,
    ) -> AssessmentSubmitResponse:
        def action(db: Session) -> AssessmentSubmitResponse:
            consume_academic_assessment_limit(db, user_id=self.user_id)
            return AcademicAssessmentService(db, self.runtime).submit(
                attempt_id,
                selected_option_id=selected_option_id,
                user_id=self.user_id,
            )

        return self._run_db("submit_assessment", action)

    def get_mastery(
        self,
        *,
        course_id: str,
        course_version: str,
    ) -> CourseMasteryResponse:
        course_id, course_version = self._validate_course_scope(
            course_id,
            course_version,
        )
        return self._run_db(
            "get_mastery",
            lambda db: AcademicAssessmentService(
                db,
                self.runtime,
            ).get_mastery(
                user_id=self.user_id,
                course_id=course_id,
                course_version=course_version,
            ),
        )

    def create_learning_plan(
        self,
        request: LearningPlanCreateRequest,
    ) -> LearningPlanResponse:
        def action(db: Session) -> LearningPlanResponse:
            consume_academic_planning_limit(db, user_id=self.user_id)
            return AcademicPlanningService(db, self.runtime).create(
                request,
                user_id=self.user_id,
            )

        return self._run_db("create_learning_plan", action)

    def approve_learning_plan(
        self,
        plan_id: str,
        *,
        confirmation: str,
    ) -> LearningPlanApprovalResponse:
        if confirmation != "APPROVE":
            raise AcademicMcpToolError(
                "Cần xác nhận chính xác APPROVE sau khi người học đồng ý."
            )

        def action(db: Session) -> LearningPlanApprovalResponse:
            consume_academic_planning_limit(db, user_id=self.user_id)
            return AcademicPlanningService(db, self.runtime).approve(
                plan_id,
                user_id=self.user_id,
            )

        return self._run_db("approve_learning_plan", action)

    def get_current_learning_plan(
        self,
        *,
        course_id: str,
        course_version: str,
    ) -> LearningPlanResponse:
        course_id, course_version = self._validate_course_scope(
            course_id,
            course_version,
        )
        return self._run_db(
            "get_current_learning_plan",
            lambda db: AcademicPlanningService(
                db,
                self.runtime,
            ).get_current(
                user_id=self.user_id,
                course_id=course_id,
                course_version=course_version,
            ),
        )

    def list_learning_events(
        self,
        *,
        course_id: str | None,
        course_version: str | None,
        limit: int,
    ) -> LearningEventListResponse:
        if limit < 1 or limit > 100:
            raise AcademicMcpToolError("limit phải nằm trong khoảng 1 đến 100.")
        if (course_id is None) != (course_version is None):
            raise AcademicMcpToolError(
                "course_id và course_version phải được truyền cùng nhau."
            )
        if course_id is not None and course_version is not None:
            course_id, course_version = self._validate_course_scope(
                course_id,
                course_version,
            )
        return self._run_db(
            "list_learning_events",
            lambda db: LearningEventService(db).list_for_user(
                user_id=self.user_id,
                course_id=course_id,
                course_version=course_version,
                limit=limit,
            ),
        )


__all__ = ["AcademicMcpToolAdapter", "AcademicMcpToolError"]
