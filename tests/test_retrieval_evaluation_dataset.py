import json
from collections import Counter
from pathlib import Path
import tempfile
import unittest

from embedding.evaluate_retrieval import load_cases
from evals.common import load_conversation_cases
from scripts.build_retrieval_cases import (
    EXPECTED_GROUP_COUNTS,
    build_cases,
    validate_cases,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RETRIEVAL_CASES_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "retrieval_cases.json"
)
CONVERSATION_CASES_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "conversation_cases.json"
)


class RetrievalEvaluationDatasetTests(unittest.TestCase):
    def test_committed_retrieval_cases_match_curated_dataset(self):
        committed_cases = load_cases(RETRIEVAL_CASES_PATH)
        expected_cases = build_cases()

        validate_cases(committed_cases)
        self.assertEqual(committed_cases, expected_cases)
        self.assertEqual(len(committed_cases), 120)
        self.assertEqual(
            Counter(case["group"] for case in committed_cases),
            Counter(EXPECTED_GROUP_COUNTS),
        )

    def test_retrieval_cases_cover_enough_distinct_food_records(self):
        cases = load_cases(RETRIEVAL_CASES_PATH)
        expected_parent_ids = {
            parent_id
            for case in cases
            for parent_id in case["expected_parent_ids"]
        }

        self.assertGreaterEqual(len(expected_parent_ids), 60)

    def test_conversation_dataset_has_unique_multi_turn_cases(self):
        cases = load_conversation_cases(CONVERSATION_CASES_PATH)

        self.assertEqual(len(cases), 10)
        self.assertEqual(len({case.id for case in cases}), len(cases))
        self.assertGreaterEqual(sum(len(case.turns) for case in cases), 20)

    def test_retrieval_case_schema_rejects_invalid_constraints(self):
        invalid_cases = [
            {
                "id": "invalid-time",
                "query": "test",
                "expected_parent_ids": [],
                "open_at": "25:00",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(
                json.dumps(invalid_cases),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_cases(path)


if __name__ == "__main__":
    unittest.main()
