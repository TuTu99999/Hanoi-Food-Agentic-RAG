import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypeVar
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from academic_agents.runtime import AcademicAgentRuntime
from academic_mcp.adapter import AcademicMcpToolAdapter, AcademicMcpToolError
from academic_mcp.config import AcademicMcpSettings
from core.config import settings
from database.connection import SessionLocal, engine
from database.schema import verify_database_revision
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


T = TypeVar("T")


@dataclass
class AcademicMcpDependencies:
    adapter: AcademicMcpToolAdapter


@asynccontextmanager
async def _production_lifespan(
    _server: MCPServer,
) -> AsyncIterator[AcademicMcpDependencies]:
    mcp_settings = AcademicMcpSettings.from_env()
    await asyncio.to_thread(
        verify_database_revision,
        engine,
        schema_check=settings.DB_SCHEMA_CHECK,
    )
    runtime = AcademicAgentRuntime.from_settings(settings)
    adapter = AcademicMcpToolAdapter(
        SessionLocal,
        runtime,
        user_id=mcp_settings.user_id,
    )
    try:
        await asyncio.to_thread(adapter.validate_identity)
        yield AcademicMcpDependencies(adapter=adapter)
    finally:
        await runtime.aclose()
        await asyncio.to_thread(engine.dispose)


def _injected_lifespan(adapter: AcademicMcpToolAdapter):
    @asynccontextmanager
    async def lifespan(
        _server: MCPServer,
    ) -> AsyncIterator[AcademicMcpDependencies]:
        yield AcademicMcpDependencies(adapter=adapter)

    return lifespan


def _adapter_from(ctx: Context) -> AcademicMcpToolAdapter:
    dependencies = ctx.request_context.lifespan_context
    if not isinstance(dependencies, AcademicMcpDependencies):
        raise ToolError("MCP academic runtime chưa sẵn sàng.")
    return dependencies.adapter


def _call_tool(action: Callable[[], T]) -> T:
    try:
        return action()
    except AcademicMcpToolError as exc:
        raise ToolError(str(exc)) from exc
    except ValidationError as exc:
        raise ToolError("Dữ liệu đầu vào của tool không hợp lệ.") from exc


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE_NON_DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
APPROVAL_ACTION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


def create_academic_mcp_server(
    *,
    adapter: AcademicMcpToolAdapter | None = None,
) -> MCPServer:
    lifespan = (
        _injected_lifespan(adapter)
        if adapter is not None
        else _production_lifespan
    )
    server = MCPServer(
        name="academic-learning-mcp",
        title="Trợ lý học tập AI đa tác tử",
        description=(
            "MCP tools dùng chung cho các môn lý luận chính trị: hỏi đáp có "
            "citation, assessment thích ứng, mastery BKT, lập kế hoạch và audit."
        ),
        instructions=(
            "Dùng ask_course_knowledge cho câu hỏi kiến thức. Assessment phải "
            "start trước rồi submit đúng attempt_id. Kế hoạch AI luôn PROPOSED; "
            "chỉ gọi approve_learning_plan sau khi người học xác nhận rõ ràng. "
            "Không tự suy đoán course_id hoặc course_version."
        ),
        version="1.0.0",
        lifespan=lifespan,
        log_level=settings.LOG_LEVEL,
    )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def ask_course_knowledge(
        question: str,
        course_id: str,
        course_version: str,
        ctx: Context,
        top_k: int = 5,
    ) -> AcademicAssistantResponse:
        """Answer one course question through Orchestrator, Knowledge and Verification agents."""

        return _call_tool(
            lambda: _adapter_from(ctx).ask_course(
                AcademicAssistantRequest(
                    question=question,
                    course_id=course_id,
                    course_version=course_version,
                    top_k=top_k,
                )
            )
        )

    @server.tool(annotations=WRITE_NON_DESTRUCTIVE, structured_output=True)
    def start_assessment(
        course_id: str,
        course_version: str,
        ctx: Context,
        concept_id: str | None = None,
    ) -> AssessmentStartResponse:
        """Start an adaptive assessment and return a question without its answer."""

        return _call_tool(
            lambda: _adapter_from(ctx).start_assessment(
                AssessmentStartRequest(
                    course_id=course_id,
                    course_version=course_version,
                    concept_id=concept_id,
                )
            )
        )

    @server.tool(annotations=WRITE_NON_DESTRUCTIVE, structured_output=True)
    def submit_assessment(
        attempt_id: UUID,
        selected_option_id: str,
        ctx: Context,
    ) -> AssessmentSubmitResponse:
        """Grade one pending attempt, update BKT and run closed-loop automation."""

        return _call_tool(
            lambda: _adapter_from(ctx).submit_assessment(
                str(attempt_id),
                selected_option_id=selected_option_id,
            )
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_course_mastery(
        course_id: str,
        course_version: str,
        ctx: Context,
    ) -> CourseMasteryResponse:
        """Read the bound learner's BKT mastery for one course version."""

        return _call_tool(
            lambda: _adapter_from(ctx).get_mastery(
                course_id=course_id,
                course_version=course_version,
            )
        )

    @server.tool(annotations=WRITE_NON_DESTRUCTIVE, structured_output=True)
    def create_learning_plan(
        course_id: str,
        course_version: str,
        target_date: date,
        minutes_per_day: int,
        ctx: Context,
        study_days: int | None = None,
        focus_concept_ids: list[str] | None = None,
        title: str | None = None,
    ) -> LearningPlanResponse:
        """Create a verified mastery-aware plan in PROPOSED state."""

        return _call_tool(
            lambda: _adapter_from(ctx).create_learning_plan(
                LearningPlanCreateRequest(
                    course_id=course_id,
                    course_version=course_version,
                    target_date=target_date,
                    study_days=study_days,
                    minutes_per_day=minutes_per_day,
                    focus_concept_ids=focus_concept_ids or [],
                    title=title,
                )
            )
        )

    @server.tool(annotations=APPROVAL_ACTION, structured_output=True)
    def approve_learning_plan(
        plan_id: UUID,
        confirmation: Literal["APPROVE"],
        ctx: Context,
    ) -> LearningPlanApprovalResponse:
        """Activate a proposed plan only after explicit human confirmation."""

        return _call_tool(
            lambda: _adapter_from(ctx).approve_learning_plan(
                str(plan_id),
                confirmation=confirmation,
            )
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_current_learning_plan(
        course_id: str,
        course_version: str,
        ctx: Context,
    ) -> LearningPlanResponse:
        """Read the active plan for one course version."""

        return _call_tool(
            lambda: _adapter_from(ctx).get_current_learning_plan(
                course_id=course_id,
                course_version=course_version,
            )
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def list_learning_events(
        ctx: Context,
        course_id: str | None = None,
        course_version: str | None = None,
        limit: int = 50,
    ) -> LearningEventListResponse:
        """Read the bound learner's closed-loop event audit trail."""

        return _call_tool(
            lambda: _adapter_from(ctx).list_learning_events(
                course_id=course_id,
                course_version=course_version,
                limit=limit,
            )
        )

    return server


mcp = create_academic_mcp_server()


if __name__ == "__main__":
    mcp.run(transport="stdio")
