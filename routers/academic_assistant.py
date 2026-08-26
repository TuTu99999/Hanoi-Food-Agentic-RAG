import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from academic_agents.runtime import AcademicRuntimeConfigurationError
from academic_retrieval.artifacts import CourseArtifactError
from academic_retrieval.service import AcademicRetrievalError
from core.security import get_current_user
from database.connection import get_db
from database.models import UserModel
from schemas.agents import AcademicAssistantRequest, AcademicAssistantResponse
from services.academic_agent_service import (
    AcademicAgentLimitError,
    consume_academic_agent_budget,
)
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/academic-assistant", tags=["Academic Agents"])


def get_academic_agent_runtime(request: Request):
    runtime = getattr(request.app.state, "academic_agent_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trợ lý học thuật chưa được bật hoặc chưa sẵn sàng.",
        )
    return runtime


@router.post("/ask", response_model=AcademicAssistantResponse)
def ask_academic_assistant(
    payload: AcademicAssistantRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime=Depends(get_academic_agent_runtime),
):
    try:
        consume_academic_agent_budget(db, user_id=current_user.id)
    except AcademicAgentLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn đã đạt giới hạn sử dụng trợ lý AI.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except Exception as exc:
        logger.exception("Academic agent budget check failed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hệ thống kiểm soát lượt dùng tạm thời chưa sẵn sàng.",
        ) from exc
    finally:
        db.close()

    try:
        response = runtime.ask(payload)
    except (
        AcademicRuntimeConfigurationError,
        AcademicRetrievalError,
        CourseArtifactError,
    ) as exc:
        logger.warning(
            "Academic agent dependency is unavailable.",
            extra={
                "course_id": payload.course_id,
                "course_version": payload.course_version,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dữ liệu của môn học chưa sẵn sàng để tra cứu.",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Academic multi-agent workflow failed.",
            extra={
                "course_id": payload.course_id,
                "course_version": payload.course_version,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Trợ lý học thuật chưa thể hoàn thành yêu cầu.",
        ) from exc

    logger.info(
        "Academic multi-agent request completed.",
        extra={
            "course_id": response.course_id,
            "course_version": response.course_version,
            "route": response.route,
            "agent_status": response.verification_status,
            "revision_count": response.revision_count,
        },
    )
    return response
