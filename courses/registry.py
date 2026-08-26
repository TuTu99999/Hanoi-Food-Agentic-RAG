from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from courses.naming import graph_namespace_for, vector_alias_for
from database.models import CourseModel, CourseVersionModel
from schemas.course import CourseManifest


class CourseConflictError(ValueError):
    pass


class CourseNotFoundError(LookupError):
    pass


class CourseRegistry:
    """Lớp nghiệp vụ nhỏ quản lý môn và các phiên bản của môn."""

    def __init__(self, db: Session):
        self.db = db

    def register_manifest(
        self,
        manifest: CourseManifest,
        *,
        created_by_user_id: int | None = None,
    ) -> CourseModel:
        course = (
            self.db.query(CourseModel)
            .filter(CourseModel.course_id == manifest.course_id)
            .first()
        )
        if course is None:
            course = CourseModel(
                course_id=manifest.course_id,
                name=manifest.name,
                domain=manifest.domain,
                language=manifest.language,
                description=manifest.description,
                created_by_user_id=created_by_user_id,
            )
            self.db.add(course)
            self.db.flush()
        elif (
            course.name != manifest.name
            or course.domain != manifest.domain
            or course.language != manifest.language
        ):
            raise CourseConflictError(
                "course_id đã tồn tại nhưng metadata môn học không khớp."
            )

        duplicate_version = (
            self.db.query(CourseVersionModel)
            .filter(
                CourseVersionModel.course_pk == course.id,
                CourseVersionModel.version == manifest.version,
            )
            .first()
        )
        if duplicate_version is not None:
            raise CourseConflictError("Phiên bản môn học đã tồn tại.")

        course_version = CourseVersionModel(
            course_pk=course.id,
            version=manifest.version,
            status="DRAFT",
            vector_alias=vector_alias_for(manifest.course_id),
            graph_namespace=graph_namespace_for(
                manifest.course_id,
                manifest.version,
            ),
            manifest_json=manifest.model_dump(mode="json"),
        )
        self.db.add(course_version)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise CourseConflictError(
                "Không thể đăng ký môn hoặc phiên bản bị trùng."
            ) from exc

        return self.get_course(manifest.course_id)

    def list_courses(self) -> list[CourseModel]:
        return (
            self.db.query(CourseModel)
            .options(selectinload(CourseModel.versions))
            .order_by(CourseModel.course_id)
            .all()
        )

    def get_course(self, course_id: str) -> CourseModel:
        course = (
            self.db.query(CourseModel)
            .options(selectinload(CourseModel.versions))
            .filter(CourseModel.course_id == course_id)
            .first()
        )
        if course is None:
            raise CourseNotFoundError("Không tìm thấy môn học.")
        return course
