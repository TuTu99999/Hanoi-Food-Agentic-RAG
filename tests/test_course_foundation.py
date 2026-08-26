from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from courses.package import CoursePackageError, load_course_package
from courses.registry import CourseConflictError, CourseRegistry
from database.base import Base
from database.models import CourseModel, CourseVersionModel
from llm.provider import (
    LLMProviderConfig,
    OpenAICompatibleProvider,
)
from schemas.course import CourseManifest


def valid_manifest(**overrides) -> CourseManifest:
    payload = {
        "course_id": "political_philosophy",
        "name": "Triết học Mác - Lênin",
        "domain": "political_theory",
        "version": "1.0.0",
        "language": "vi",
    }
    payload.update(overrides)
    return CourseManifest.model_validate(payload)


class CourseManifestTests(unittest.TestCase):
    def test_manifest_uses_safe_defaults(self):
        manifest = valid_manifest()

        self.assertTrue(manifest.retrieval.dense)
        self.assertTrue(manifest.retrieval.keyword)
        self.assertTrue(manifest.retrieval.graph_expansion)
        self.assertEqual(manifest.assessment.mastery_model, "bkt")
        self.assertEqual(
            manifest.assessment.allowed_question_types,
            ["multiple_choice", "short_answer"],
        )
        self.assertTrue(manifest.automation.adaptive_replanning)

    def test_manifest_rejects_invalid_course_id_version_and_extra_fields(self):
        for updates in (
            {"course_id": "Triết học"},
            {"version": "v1"},
            {"unknown_setting": True},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                valid_manifest(**updates)

    def test_manifest_removes_duplicate_question_types(self):
        manifest = valid_manifest(
            assessment={
                "mastery_model": "bkt",
                "allowed_question_types": [
                    "multiple_choice",
                    "multiple_choice",
                    "short_answer",
                ],
            }
        )
        self.assertEqual(
            manifest.assessment.allowed_question_types,
            ["multiple_choice", "short_answer"],
        )

    def test_manifest_rejects_unsafe_or_duplicate_sources(self):
        valid_source = {
            "path": "documents/textbook.pdf",
            "document_id": "official_textbook",
            "title": "Giáo trình chính thức",
            "source_type": "official_textbook",
        }
        with self.assertRaises(ValidationError):
            valid_manifest(
                sources=[{**valid_source, "path": "../secret.pdf"}]
            )
        with self.assertRaises(ValidationError):
            valid_manifest(sources=[valid_source, valid_source])


class CoursePackageTests(unittest.TestCase):
    def test_loads_minimal_yaml_course_package(self):
        with tempfile.TemporaryDirectory(prefix="course-package-") as directory:
            root = Path(directory)
            (root / "documents").mkdir()
            (root / "documents" / "chapter-1.md").write_text(
                "# Chương 1\nNội dung kiểm thử.",
                encoding="utf-8",
            )
            (root / "course.yaml").write_text(
                "\n".join(
                    [
                        "course_id: political_philosophy",
                        "name: Triết học Mác - Lênin",
                        "domain: political_theory",
                        "version: 1.0.0",
                        "language: vi",
                    ]
                ),
                encoding="utf-8",
            )

            result = load_course_package(root)

        self.assertEqual(result.manifest.course_id, "political_philosophy")
        self.assertEqual(len(result.documents), 1)

    def test_rejects_package_without_a_real_document(self):
        with tempfile.TemporaryDirectory(prefix="course-package-") as directory:
            root = Path(directory)
            (root / "documents").mkdir()
            (root / "documents" / "README.md").write_text(
                "Hướng dẫn",
                encoding="utf-8",
            )
            (root / "course.yaml").write_text(
                "\n".join(
                    [
                        "course_id: political_philosophy",
                        "name: Triết học Mác - Lênin",
                        "version: 1.0.0",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(CoursePackageError):
                load_course_package(root)

    def test_rejects_manifest_that_points_to_a_missing_document(self):
        with tempfile.TemporaryDirectory(prefix="course-package-") as directory:
            root = Path(directory)
            (root / "documents").mkdir()
            (root / "documents" / "available.md").write_text(
                "Nội dung có sẵn.",
                encoding="utf-8",
            )
            (root / "course.yaml").write_text(
                "\n".join(
                    [
                        "course_id: political_philosophy",
                        "name: Triết học Mác - Lênin",
                        "version: 1.0.0",
                        "sources:",
                        "  - path: documents/missing.pdf",
                        "    document_id: official_textbook",
                        "    title: Giáo trình chính thức",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(CoursePackageError):
                load_course_package(root)


class CourseRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://")
        cls.session_factory = sessionmaker(bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)
        cls.engine.dispose()

    def setUp(self):
        self.db = self.session_factory()
        self.db.query(CourseVersionModel).delete()
        self.db.query(CourseModel).delete()
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_registers_course_and_adds_a_new_version(self):
        registry = CourseRegistry(self.db)
        course = registry.register_manifest(valid_manifest())

        self.assertEqual(course.course_id, "political_philosophy")
        self.assertEqual(course.versions[0].status, "DRAFT")
        self.assertEqual(
            course.versions[0].vector_alias,
            "course_political_philosophy_current",
        )

        next_version = valid_manifest(version="1.1.0")
        updated_course = registry.register_manifest(next_version)
        self.assertEqual(
            [version.version for version in updated_course.versions],
            ["1.0.0", "1.1.0"],
        )

    def test_rejects_duplicate_version_and_mismatched_metadata(self):
        registry = CourseRegistry(self.db)
        registry.register_manifest(valid_manifest())

        with self.assertRaises(CourseConflictError):
            registry.register_manifest(valid_manifest())
        with self.assertRaises(CourseConflictError):
            registry.register_manifest(
                valid_manifest(version="2.0.0", name="Tên môn khác")
            )


class FakeClient:
    def close(self):
        return None


class FakeAsyncClient:
    async def close(self):
        return None


class LLMProviderTests(unittest.TestCase):
    def test_openai_compatible_provider_keeps_provider_identity(self):
        calls = []

        def sync_factory(**options):
            calls.append(("sync", options))
            return FakeClient()

        def async_factory(**options):
            calls.append(("async", options))
            return FakeAsyncClient()

        provider = OpenAICompatibleProvider(
            LLMProviderConfig(
                provider="kimi",
                api_key="test-key",
                base_url="https://api.moonshot.ai/v1",
                model="kimi-k3",
                timeout_seconds=20,
            ),
            sync_client_factory=sync_factory,
            async_client_factory=async_factory,
        )

        self.assertEqual(provider.name, "kimi")
        self.assertEqual(provider.model, "kimi-k3")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
