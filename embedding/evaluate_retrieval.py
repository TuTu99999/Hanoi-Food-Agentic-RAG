import argparse
import json
import time
from pathlib import Path
import sys

import numpy as np

from embedding.retrieval_engine import RetrievalEngine, normalize_text


DEFAULT_CASES_PATH = Path("data/evaluation/retrieval_cases.json")


def load_cases(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("Bộ đánh giá retrieval phải là một danh sách không rỗng.")
    return cases


def evaluate_threshold(
    retriever: RetrievalEngine,
    cases: list[dict],
    threshold: float,
    top_k: int = 5,
) -> dict:
    passed = 0
    reciprocal_rank_total = 0.0
    recall_total = 0.0
    recall_case_count = 0
    district_filter_passed = 0
    district_filter_case_count = 0
    latencies_ms = []
    failures = []

    for case in cases:
        started_at = time.perf_counter()
        results = retriever.search(
            query=case["query"],
            top_k=top_k,
            district_filter=case.get("district"),
            domain_filter=case.get("domain"),
            category_filter=case.get("category"),
            min_score=threshold,
        )
        latencies_ms.append(
            (time.perf_counter() - started_at) * 1000
        )
        actual_ids = [result.get("parent_id") for result in results]
        expected_ids = set(case.get("expected_parent_ids", []))
        matched_ids = expected_ids.intersection(actual_ids)

        if not expected_ids:
            success = not actual_ids
            rank = None
        else:
            recall_total += len(matched_ids) / len(expected_ids)
            recall_case_count += 1
            rank = next(
                (
                    index
                    for index, parent_id in enumerate(actual_ids, start=1)
                    if parent_id in expected_ids
                ),
                None,
            )
            success = rank is not None

        expected_district = normalize_text(case.get("district"))
        if expected_district:
            district_filter_case_count += 1
            if results:
                district_matches = all(
                    normalize_text(result.get("district"))
                    == expected_district
                    for result in results
                )
            else:
                district_matches = not expected_ids
            if district_matches:
                district_filter_passed += 1

        if success:
            passed += 1
            if rank:
                reciprocal_rank_total += 1 / rank
        else:
            failures.append(
                {
                    "query": case["query"],
                    "expected": sorted(expected_ids),
                    "actual": actual_ids,
                }
            )

    total = len(cases)
    return {
        "threshold": threshold,
        "top_k": top_k,
        "passed": passed,
        "total": total,
        "accuracy": passed / total,
        f"recall_at_{top_k}": (
            recall_total / recall_case_count
            if recall_case_count
            else 0.0
        ),
        "mrr": (
            reciprocal_rank_total / recall_case_count
            if recall_case_count
            else 0.0
        ),
        "district_filter_accuracy": (
            district_filter_passed / district_filter_case_count
            if district_filter_case_count
            else 0.0
        ),
        "latency_ms": {
            "mean": float(np.mean(latencies_ms)),
            "p50": float(np.percentile(latencies_ms, 50)),
            "p95": float(np.percentile(latencies_ms, 95)),
        },
        "estimated_cost_usd": 0.0,
        "failures": failures,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Đánh giá retrieval trên alias Qdrant hiện tại.",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
    )
    parser.add_argument(
        "--thresholds",
        type=float,
        nargs="+",
        default=[0.45, 0.5, 0.55],
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k phải lớn hơn 0")

    retriever = RetrievalEngine()
    try:
        cases = load_cases(args.cases)
        reports = [
            evaluate_threshold(
                retriever,
                cases,
                threshold,
                top_k=args.top_k,
            )
            for threshold in args.thresholds
        ]

        for report in reports:
            print(
                f"threshold={report['threshold']:.2f} "
                f"accuracy={report['accuracy']:.1%} "
                f"recall@{args.top_k}="
                f"{report[f'recall_at_{args.top_k}']:.1%} "
                f"district={report['district_filter_accuracy']:.1%} "
                f"MRR={report['mrr']:.3f} "
                f"p95={report['latency_ms']['p95']:.1f}ms "
                f"({report['passed']}/{report['total']})"
            )
            for failure in report["failures"]:
                print(
                    f"  FAIL: {failure['query']} | "
                    f"expected={failure['expected']} | "
                    f"actual={failure['actual']}"
                )

        best_report = max(
            reports,
            key=lambda report: (
                report["accuracy"],
                report[f"recall_at_{args.top_k}"],
                report["mrr"],
            ),
        )
        print(
            "Ngưỡng đề xuất từ bộ đánh giá hiện tại: "
            f"{best_report['threshold']:.2f}"
        )

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as file:
                json.dump(
                    reports,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
