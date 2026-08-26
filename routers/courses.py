from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.security import get_content_manager, get_current_user
from courses.naming import graph_namespace_for, vector_alias_for
from courses.registry import (
    CourseConflictError,
    CourseNotFoundError,
    CourseRegistry,
)
from database.connection import get_db
from database.models import CourseModel, UserModel
from schemas.course import (
    CourseManifest,
    CourseManifestValidationResponse,
    CourseResponse,
    CourseStatus,
    CourseVersionResponse,
)


router = APIRouter(prefix="/courses", tags=["Courses"])


def _course_response(course: CourseModel) -> CourseResponse:
    versions = [
        CourseVersionResponse(
            version=version.version,
            status=CourseStatus(version.status),
            vector_alias=version.vector_alias,
            graph_namespace=version.graph_namespace,
            manifest=CourseManifest.model_validate(version.manifest_json),
            created_at=version.created_at,
            activated_at=version.activated_at,
        )
        for version in course.versions
    ]
    return CourseResponse(
        course_id=course.course_id,
        name=course.name,
        domain=course.domain,
        language=course.language,
        description=course.description,
        created_at=course.created_at,
        versions=versions,
    )


@router.post(
    "/validate-manifest",
    response_model=CourseManifestValidationResponse,
)
def validate_course_manifest(
    manifest: CourseManifest,
    _current_user: UserModel = Depends(get_content_manager),
):
    return CourseManifestValidationResponse(
        course_id=manifest.course_id,
        version=manifest.version,
        vector_alias=vector_alias_for(manifest.course_id),
        graph_namespace=graph_namespace_for(
            manifest.course_id,
            manifest.version,
        ),
    )


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
def register_course(
    manifest: CourseManifest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_content_manager),
):
    try:
        course = CourseRegistry(db).register_manifest(
            manifest,
            created_by_user_id=current_user.id,
        )
    except CourseConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _course_response(course)


@router.get("", response_model=list[CourseResponse])
def list_courses(
    db: Session = Depends(get_db),
    _current_user: UserModel = Depends(get_current_user),
):
    return [
        _course_response(course)
        for course in CourseRegistry(db).list_courses()
    ]


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: str,
    db: Session = Depends(get_db),
    _current_user: UserModel = Depends(get_current_user),
):
    try:
        course = CourseRegistry(db).get_course(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _course_response(course)
