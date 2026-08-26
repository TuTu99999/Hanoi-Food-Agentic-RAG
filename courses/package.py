import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from assessment.question_bank import QuestionBankError, load_question_bank
from planning.learning_map import LearningMapError, load_learning_map
from schemas.assessment import AssessmentQuestionBank
from schemas.course import CourseManifest
from schemas.planning import LearningMap


MANIFEST_NAMES = ("course.yaml", "course.yml", "course.json")
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_MANIFEST_BYTES = 256 * 1024
MAX_DOCUMENTS = 100
MAX_TOTAL_DOCUMENT_BYTES = 200 * 1024 * 1024


class CoursePackageError(ValueError):
    pass


@dataclass(frozen=True)
class CoursePackageResult:
    root: Path
    manifest_path: Path
    manifest: CourseManifest
    documents: tuple[Path, ...]
    question_bank_path: Path | None
    question_bank: AssessmentQuestionBank | None
    learning_map_path: Path | None
    learning_map: LearningMap | None


def _read_manifest(path: Path) -> dict:
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise CoursePackageError("Course manifest vượt quá 256 KB.")
    try:
        raw_text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            payload = json.loads(raw_text)
        else:
            payload = yaml.safe_load(raw_text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise CoursePackageError("Không thể đọc course manifest hợp lệ.") from exc
    if not isinstance(payload, dict):
        raise CoursePackageError("Course manifest phải là một object.")
    return payload


def load_course_package(package_path: str | Path) -> CoursePackageResult:
    """Kiểm tra cấu trúc tối thiểu của một Course Package trên máy chủ."""

    root = Path(package_path).resolve()
    if not root.is_dir():
        raise CoursePackageError("Course Package không tồn tại hoặc không phải thư mục.")

    manifest_paths = [root / name for name in MANIFEST_NAMES if (root / name).is_file()]
    if len(manifest_paths) != 1:
        raise CoursePackageError(
            "Course Package phải có đúng một file course.yaml, course.yml hoặc course.json."
        )

    documents_directory = root / "documents"
    if not documents_directory.is_dir():
        raise CoursePackageError("Course Package thiếu thư mục documents.")

    document_paths = []
    total_document_bytes = 0
    for path in documents_directory.rglob("*"):
        if (
            not path.is_file()
            or path.name.lower() == "readme.md"
            or path.suffix.lower() not in DOCUMENT_EXTENSIONS
        ):
            continue
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(root)
        except ValueError as exc:
            raise CoursePackageError(
                "Tài liệu không được trỏ ra ngoài Course Package."
            ) from exc
        document_paths.append(resolved_path)
        total_document_bytes += resolved_path.stat().st_size

    documents = tuple(sorted(document_paths))
    if not documents:
        raise CoursePackageError(
            "Thư mục documents phải có ít nhất một file PDF, DOCX, TXT hoặc Markdown."
        )
    if len(documents) > MAX_DOCUMENTS:
        raise CoursePackageError("Course Package chỉ hỗ trợ tối đa 100 tài liệu.")
    if total_document_bytes > MAX_TOTAL_DOCUMENT_BYTES:
        raise CoursePackageError("Tổng dung lượng tài liệu vượt quá 200 MB.")

    try:
        manifest = CourseManifest.model_validate(_read_manifest(manifest_paths[0]))
    except ValidationError as exc:
        raise CoursePackageError(f"Course manifest không hợp lệ: {exc}") from exc

    available_paths = {
        path.relative_to(root).as_posix().casefold()
        for path in documents
    }
    missing_sources = [
        source.path
        for source in manifest.sources
        if source.path.casefold() not in available_paths
    ]
    if missing_sources:
        raise CoursePackageError(
            "Không tìm thấy tài liệu đã khai báo: "
            + ", ".join(missing_sources)
        )

    question_bank_path = root / "assessment" / "questions.json"
    question_bank = None
    if question_bank_path.is_file():
        resolved_bank_path = question_bank_path.resolve()
        try:
            resolved_bank_path.relative_to(root)
        except ValueError as exc:
            raise CoursePackageError(
                "Ngân hàng câu hỏi không được trỏ ra ngoài Course Package."
            ) from exc
        try:
            question_bank = load_question_bank(
                resolved_bank_path,
                expected_course_id=manifest.course_id,
                expected_course_version=manifest.version,
            )
        except QuestionBankError as exc:
            raise CoursePackageError(str(exc)) from exc
        available_source_paths = {
            path.relative_to(root).as_posix().casefold()
            for path in documents
        }
        missing_question_sources = sorted(
            {
                question.citation.source_path
                for question in question_bank.questions
                if question.citation.source_path.casefold()
                not in available_source_paths
            }
        )
        if missing_question_sources:
            raise CoursePackageError(
                "Citation câu hỏi trỏ tới tài liệu không tồn tại: "
                + ", ".join(missing_question_sources)
            )

    learning_map_path = root / "planning" / "learning_map.json"
    learning_map = None
    if learning_map_path.is_file():
        resolved_learning_map_path = learning_map_path.resolve()
        try:
            resolved_learning_map_path.relative_to(root)
        except ValueError as exc:
            raise CoursePackageError(
                "Learning Map không được trỏ ra ngoài Course Package."
            ) from exc
        try:
            learning_map = load_learning_map(
                resolved_learning_map_path,
                expected_course_id=manifest.course_id,
                expected_course_version=manifest.version,
            )
        except LearningMapError as exc:
            raise CoursePackageError(str(exc)) from exc
        available_source_paths = {
            path.relative_to(root).as_posix().casefold()
            for path in documents
        }
        missing_learning_sources = sorted(
            {
                concept.citation.source_path
                for concept in learning_map.concepts
                if concept.citation.source_path.casefold()
                not in available_source_paths
            }
        )
        if missing_learning_sources:
            raise CoursePackageError(
                "Citation Learning Map trỏ tới tài liệu không tồn tại: "
                + ", ".join(missing_learning_sources)
            )
        if question_bank is not None:
            map_concepts = {
                concept.concept_id for concept in learning_map.concepts
            }
            question_concepts = {
                question.concept_id for question in question_bank.questions
            }
            missing_question_concepts = question_concepts - map_concepts
            if missing_question_concepts:
                raise CoursePackageError(
                    "Concept câu hỏi chưa có trong Learning Map: "
                    + ", ".join(sorted(missing_question_concepts))
                )

    return CoursePackageResult(
        root=root,
        manifest_path=manifest_paths[0],
        manifest=manifest,
        documents=documents,
        question_bank_path=(
            question_bank_path.resolve() if question_bank is not None else None
        ),
        question_bank=question_bank,
        learning_map_path=(
            learning_map_path.resolve() if learning_map is not None else None
        ),
        learning_map=learning_map,
    )
