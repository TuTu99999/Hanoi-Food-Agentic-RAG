import json
import threading
from pathlib import Path

from pydantic import ValidationError

from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from schemas.planning import LearningMap


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_LEARNING_MAP_BYTES = 5 * 1024 * 1024


class LearningMapError(ValueError):
    pass


def load_learning_map(
    path: str | Path,
    *,
    expected_course_id: str | None = None,
    expected_course_version: str | None = None,
) -> LearningMap:
    resolved_path = Path(path).resolve()
    try:
        if resolved_path.stat().st_size > MAX_LEARNING_MAP_BYTES:
            raise LearningMapError("Learning Map vượt quá 5 MB.")
        with resolved_path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except LearningMapError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningMapError("Không thể đọc Learning Map JSON.") from exc
    try:
        learning_map = LearningMap.model_validate(payload)
    except ValidationError as exc:
        raise LearningMapError(f"Learning Map không đúng schema: {exc}") from exc
    if expected_course_id and learning_map.course_id != expected_course_id:
        raise LearningMapError("Learning Map bị lẫn môn.")
    if expected_course_version and learning_map.course_version != expected_course_version:
        raise LearningMapError("Learning Map sai phiên bản môn.")
    return learning_map


class LearningMapRegistry:
    def __init__(self, data_root: str | Path) -> None:
        root = Path(data_root)
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        self.data_root = root.resolve()
        self._maps: dict[tuple[str, str], LearningMap] = {}
        self._lock = threading.Lock()

    def _map_path(self, course_id: str, course_version: str) -> Path:
        if not COURSE_ID_PATTERN.fullmatch(course_id):
            raise LearningMapError("course_id không hợp lệ.")
        if not VERSION_PATTERN.fullmatch(course_version):
            raise LearningMapError("course_version không hợp lệ.")
        path = (
            self.data_root
            / course_id
            / course_version
            / "planning"
            / "learning_map.json"
        ).resolve()
        try:
            path.relative_to(self.data_root)
        except ValueError as exc:
            raise LearningMapError("Đường dẫn Learning Map không an toàn.") from exc
        return path

    def get(self, course_id: str, course_version: str) -> LearningMap:
        key = (course_id, course_version)
        cached = self._maps.get(key)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._maps.get(key)
            if cached is not None:
                return cached
            learning_map = load_learning_map(
                self._map_path(course_id, course_version),
                expected_course_id=course_id,
                expected_course_version=course_version,
            )
            self._maps[key] = learning_map
            return learning_map

    def clear(self) -> None:
        with self._lock:
            self._maps.clear()
