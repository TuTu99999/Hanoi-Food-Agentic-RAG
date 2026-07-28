import argparse
import json
from collections import Counter
from pathlib import Path

from rag.query_router import ALLOWED_INTENTS, QueryRouter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "query_router_cases.json"
)


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as cases_file:
        cases = json.load(cases_file)

    if not isinstance(cases, list) or not cases:
        raise ValueError("Query router cases must be a non-empty list")

    case_ids = set()
    validated_cases = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Invalid case at index {index}")

        case_id = case.get("id")
        text = case.get("text")
        expected_intent = case.get("expected_intent")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"Invalid case id at index {index}")
        if case_id in case_ids:
            raise ValueError(f"Duplicate case id at index {index}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Invalid case text at index {index}")
        if expected_intent not in ALLOWED_INTENTS:
            raise ValueError(f"Invalid expected intent at index {index}")

        case_ids.add(case_id)
        validated_cases.append(
            {
                "id": case_id,
                "text": text.strip(),
                "expected_intent": expected_intent,
            }
        )

    return validated_cases


def evaluate(
    router: QueryRouter,
    cases: list[dict[str, str]],
) -> dict:
    correct = 0
    high_confidence = 0
    high_confidence_correct = 0
    confusion = Counter()

    for case in cases:
        prediction = router.predict(case["text"])
        expected = case["expected_intent"]
        predicted = prediction.intent
        is_correct = predicted == expected

        correct += int(is_correct)
        confusion[(expected, predicted)] += 1

        if prediction.confidence >= router.confidence_threshold:
            high_confidence += 1
            high_confidence_correct += int(is_correct)

    total = len(cases)
    confusion_counts = [
        {
            "expected": expected,
            "predicted": predicted,
            "count": count,
        }
        for (expected, predicted), count in sorted(confusion.items())
    ]
    return {
        "total": total,
        "intent_accuracy": correct / total,
        "confidence_threshold": router.confidence_threshold,
        "high_confidence_coverage": high_confidence / total,
        "high_confidence_accuracy": (
            high_confidence_correct / high_confidence
            if high_confidence
            else None
        ),
        "confusion_counts": confusion_counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the local query intent router.",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
    )
    parser.add_argument("--dataset", type=Path)
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.35,
    )
    parser.add_argument("--min-accuracy", type=float)
    args = parser.parse_args()

    if not 0 <= args.confidence_threshold <= 1:
        parser.error("--confidence-threshold must be between 0 and 1")
    if args.min_accuracy is not None and not 0 <= args.min_accuracy <= 1:
        parser.error("--min-accuracy must be between 0 and 1")
    return args


def main() -> int:
    args = parse_args()
    router = QueryRouter(
        dataset_path=args.dataset,
        confidence_threshold=args.confidence_threshold,
    )
    report = evaluate(router, load_cases(args.cases))
    print(json.dumps(report, indent=2))

    if (
        args.min_accuracy is not None
        and report["intent_accuracy"] < args.min_accuracy
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
