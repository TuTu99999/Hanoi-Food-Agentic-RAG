import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evals.business_rules import evaluate_business_rules
from evals.common import (
    GoldenCase,
    context_to_text,
    evaluation_metadata,
    fact_coverage,
    failed_ragas_metrics,
    parse_case,
    parse_conversation_case,
)


class EvaluationSupportTests(unittest.TestCase):
    def test_case_validation_and_reference_fallback(self):
        case = parse_case(
            {
                "id": "food-1",
                "question": "Quán ở đâu?",
                "expected_facts": ["12 Tràng Tiền", "Hoàn Kiếm"],
            }
        )

        self.assertIn("12 Tràng Tiền", case.reference)
        self.assertEqual(case.expected_facts, ("12 Tràng Tiền", "Hoàn Kiếm"))

        with self.assertRaises(ValueError):
            parse_case(
                {
                    "id": "invalid",
                    "question": "test",
                    "expected_facts": [],
                }
            )

    def test_context_serialization_does_not_leak_unknown_payload(self):
        serialized = context_to_text(
            {
                "title": "Phở Test",
                "district": "Cầu Giấy",
                "content": "Dữ liệu kiểm thử",
                "internal_secret": "must-not-appear",
            }
        )

        self.assertIn("Phở Test", serialized)
        self.assertNotIn("internal_secret", serialized)
        self.assertNotIn("must-not-appear", serialized)

    def test_fact_coverage_is_accent_and_case_insensitive(self):
        self.assertEqual(
            fact_coverage(
                "Quán nằm tại HOAN KIEM, giá 50.000Đ.",
                ("Hoàn Kiếm", "50.000đ"),
            ),
            1.0,
        )

    def test_business_rule_score_combines_facts_and_hard_filter(self):
        case = GoldenCase(
            id="food-2",
            question="Phở ở Cầu Giấy?",
            expected_facts=("Phở Test",),
            reference="Phở Test ở Cầu Giấy.",
            district="Cầu Giấy",
        )
        passed = evaluate_business_rules(
            case,
            answer="Bạn có thể thử Phở Test.",
            documents=[{"district": "cau giay"}],
        )
        failed = evaluate_business_rules(
            case,
            answer="Bạn có thể thử quán khác.",
            documents=[{"district": "Hoàn Kiếm"}],
        )

        self.assertTrue(passed.passed)
        self.assertEqual(passed.score, 1.0)
        self.assertFalse(failed.passed)
        self.assertEqual(failed.score, 0.0)

    def test_no_context_rule_rejects_fabricated_context(self):
        case = GoldenCase(
            id="food-empty",
            question="Sushi ở Ba Vì?",
            expected_facts=("không tìm thấy",),
            reference="Không tìm thấy dữ liệu.",
            district="Ba Vì",
            expect_no_context=True,
        )
        result = evaluate_business_rules(
            case,
            answer="Không tìm thấy dữ liệu phù hợp.",
            documents=[],
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

    def test_conversation_case_requires_multiple_turns(self):
        case = parse_conversation_case(
            {
                "id": "conversation-1",
                "scenario": "User changes the budget direction.",
                "expected_outcome": "The latest direction is applied.",
                "turns": [
                    {"user_input": "Giá 50k đổ về."},
                    {"user_input": "Đổi thành 50k đổ lên."},
                ],
            }
        )

        self.assertEqual(len(case.turns), 2)
        with self.assertRaises(ValueError):
            parse_conversation_case(
                {
                    "id": "invalid",
                    "scenario": "test",
                    "expected_outcome": "test",
                    "turns": [{"user_input": "only one"}],
                }
            )

    def test_ragas_fails_when_no_case_was_evaluated(self):
        summary = {
            "evaluated_cases": 0,
            "skipped_cases": 1,
            "metrics": {
                "faithfulness": None,
                "context_precision": None,
            },
        }

        self.assertIn(
            "evaluated_cases",
            failed_ragas_metrics(summary, minimum_score=0.7),
        )

    def test_evaluation_metadata_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            cases_path = Path(directory) / "cases.json"
            cases_path.write_text("[]", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"EVALUATION_SOURCE_SHA": "abc123"},
            ):
                metadata = evaluation_metadata(
                    cases_path=cases_path,
                    collection="food_v2",
                    embedding_model="test-model",
                )

        self.assertEqual(metadata["source_sha"], "abc123")
        self.assertEqual(metadata["collection"], "food_v2")
        self.assertEqual(len(metadata["dataset_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
