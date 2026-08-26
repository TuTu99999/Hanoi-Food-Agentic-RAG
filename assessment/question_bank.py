import json
import threading
from pathlib import Path

from pydantic import ValidationError

from schemas.assessment import AssessmentQuestionBank
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_QUESTION_BANK_BYTES = 5 * 1024 * 1024


class QuestionBankError(ValueError):
    pass


def load_question_bank(
    path: str | Path,
    *,
    expected_course_id: str | None = None,
    expected_course_version: str | None = None,
) -> AssessmentQuestionBank:
    resolved_path = Path(path).resolve()
    try:
        if resolved_path.stat().st_size > MAX_QUESTION_BANK_BYTES:
            raise QuestionBankError("Ngân hàng câu hỏi vượt quá 5 MB.")
        with resolved_path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except QuestionBankError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionBankError("Không thể đọc ngân hàng câu hỏi JSON.") from exc

    try:
        bank = AssessmentQuestionBank.model_validate(payload)
    except ValidationError as exc:
        raise QuestionBankError(
            f"Ngân hàng câu hỏi không đúng schema: {exc}"
        ) from exc
    if expected_course_id and bank.course_id != expected_course_id:
        raise QuestionBankError("Ngân hàng câu hỏi bị lẫn môn.")
    if expected_course_version and bank.course_version != expected_course_version:
        raise QuestionBankError("Ngân hàng câu hỏi sai phiên bản môn.")
    return bank


class QuestionBankRegistry:
    """Load and cache one normalized question bank per course version."""

    def __init__(self, data_root: str | Path) -> None:
        root = Path(data_root)
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        self.data_root = root.resolve()
        self._banks: dict[tuple[str, str], AssessmentQuestionBank] = {}
        self._lock = threading.Lock()

    def _bank_path(self, course_id: str, course_version: str) -> Path:
        if not COURSE_ID_PATTERN.fullmatch(course_id):
            raise QuestionBankError("course_id không hợp lệ.")
        if not VERSION_PATTERN.fullmatch(course_version):
            raise QuestionBankError("course_version không hợp lệ.")
        path = (
            self.data_root
            / course_id
            / course_version
            / "assessment"
            / "questions.json"
        ).resolve()
        try:
            path.relative_to(self.data_root)
        except ValueError as exc:
            raise QuestionBankError("Đường dẫn ngân hàng câu hỏi không an toàn.") from exc
        return path

    def get(self, course_id: str, course_version: str) -> AssessmentQuestionBank:
        key = (course_id, course_version)
        cached = self._banks.get(key)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._banks.get(key)
            if cached is not None:
                return cached
            bank = load_question_bank(
                self._bank_path(course_id, course_version),
                expected_course_id=course_id,
                expected_course_version=course_version,
            )
            self._banks[key] = bank
            return bank

    def clear(self) -> None:
        with self._lock:
            self._banks.clear()
