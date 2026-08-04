import json
import re
import unicodedata
import unittest
from collections import Counter
from pathlib import Path

from rag.query_router import ALLOWED_INTENTS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAIN_PATH = PROJECT_ROOT / "data" / "query_router" / "intents.jsonl"
EVAL_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "query_router_cases.json"
)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _load_train() -> list[dict]:
    return [
        json.loads(line)
        for line in TRAIN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_eval() -> list[dict]:
    return json.loads(EVAL_PATH.read_text(encoding="utf-8"))


class QueryRouterDatasetTests(unittest.TestCase):
    def test_datasets_are_balanced_and_large_enough(self):
        train_counts = Counter(row["label"] for row in _load_train())
        eval_counts = Counter(
            row["expected_intent"] for row in _load_eval()
        )

        self.assertEqual(set(train_counts), ALLOWED_INTENTS)
        self.assertEqual(set(eval_counts), ALLOWED_INTENTS)
        self.assertEqual(set(train_counts.values()), {70})
        self.assertEqual(set(eval_counts.values()), {25})

    def test_datasets_have_unique_identifiers_and_texts(self):
        train_rows = _load_train()
        eval_rows = _load_eval()

        train_ids = [row["group_id"] for row in train_rows]
        eval_ids = [row["id"] for row in eval_rows]
        train_texts = [_normalize(row["text"]) for row in train_rows]
        eval_texts = [_normalize(row["text"]) for row in eval_rows]

        self.assertEqual(len(train_ids), len(set(train_ids)))
        self.assertEqual(len(eval_ids), len(set(eval_ids)))
        self.assertEqual(len(train_texts), len(set(train_texts)))
        self.assertEqual(len(eval_texts), len(set(eval_texts)))
        self.assertTrue(set(train_texts).isdisjoint(eval_texts))


if __name__ == "__main__":
    unittest.main()
