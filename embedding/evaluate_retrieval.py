import argparse
import json
import time
from collections import Counter
from pathlib import Path
import sys

import numpy as np

from embedding.catalog_schema import is_open_at
from embedding.retrieval_engine import RetrievalEngine, normalize_text


DEFAULT_CASES_PATH = Path("data/evaluation/retrieval_cases.json")


def load_cases(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("Bộ đánh giá retrieval phải là một danh sách không rỗng.")
    case_ids = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Case retrieval {index} phải là một object.")
        case_id = str(case.get("id") or "").strip()
        query = str(case.get("query") or "").strip()
        expected_ids = case.get("expected_parent_ids")
        if not case_id or case_id in case_ids:
            raise ValueError("Mỗi case retrieval phải có id duy nhất.")
        if not query:
            raise ValueError(f"{case_id} thiếu query.")
        if not isinstance(expected_ids, list):
            raise ValueError(
                f"{case_id}.expected_parent_ids phải là một danh sách."
            )
        if not all(
            isinstance(parent_id, str) and parent_id.strip()
            for parent_id in expected_ids
        ):
            raise ValueError(
                f"{case_id}.expected_parent_ids chứa id không hợp lệ."
            )
        for field in ("price_min", "price_max"):
            value = case.get(field)
            if value is not None and (
                not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{case_id}.{field} không hợp lệ.")
        min_unique_parent_ids = case.get("min_unique_parent_ids")
        if min_unique_parent_ids is not None and (
            not isinstance(min_unique_parent_ids, int)
            or min_unique_parent_ids <= 0
        ):
            raise ValueError(
                f"{case_id}.min_unique_parent_ids không hợp lệ."
            )
        if (
            case.get("price_min") is not None
            and case.get("price_max") is not None
            and case["price_min"] > case["price_max"]
        ):
            raise ValueError(f"{case_id} có khoảng giá không hợp lệ.")
        open_at = case.get("open_at")
        if open_at is not None:
            try:
                hour_text, minute_text = open_at.split(":")
                hour = int(hour_text)
                minute = int(minute_text)
            except (AttributeError, TypeError, ValueError):
                raise ValueError(
                    f"{case_id}.open_at phải có định dạng HH:MM."
                ) from None
            if (
                len(hour_text) != 2
                or len(minute_text) != 2
                or not 0 <= hour <= 23
                or not 0 <= minute <= 59
            ):
                raise ValueError(
                    f"{case_id}.open_at phải có định dạng HH:MM."
                )
        case_ids.add(case_id)
    return cases


def matches_case_constraints(result: dict, case: dict) -> bool:
    expected_district = normalize_text(case.get("district"))
    if (
        expected_district
        and normalize_text(result.get("district")) != expected_district
    ):
        return False

    price_min = case.get("price_min")
    if price_min is not None:
        result_price_max = result.get("price_max")
        if (
            not isinstance(result_price_max, int)
            or result_price_max < price_min
        ):
            return False

    price_max = case.get("price_max")
    if price_max is not None:
        result_price_min = result.get("price_min")
        if (
            not isinstance(result_price_min, int)
            or result_price_min > price_max
        ):
            return False

    open_at = case.get("open_at")
    if open_at and not is_open_at(
        result.get("opening_intervals"),
        open_at,
    ):
        return False

    return True


def evaluate_threshold(
    retriever: RetrievalEngine,
    cases: list[dict],
    threshold: float,
    top_k: int = 5,
    search_modes: tuple[str, ...] | None = None,
) -> dict:
    passed = 0
    reciprocal_rank_total = 0.0
    recall_total = 0.0
    recall_case_count = 0
    district_filter_passed = 0
    district_filter_case_count = 0
    latencies_ms = []
    failures = []
    branch_error_counts: Counter = Counter()
    branch_result_counts: Counter = Counter()
    exact_shortcut_cases = 0
    group_totals: Counter = Counter()
    group_passed: Counter = Counter()
    constraint_cases = 0
    constraint_passed = 0
    diversity_cases = 0
    diversity_passed = 0
    returned_parent_ids = set()
    top_result_ids = set()
    group_result_ids: dict[str, set[str]] = {}
    group_top_result_ids: dict[str, set[str]] = {}

    for case in cases:
        case_group = str(case.get("group") or "unclassified")
        group_totals[case_group] += 1
        group_result_ids.setdefault(case_group, set())
        group_top_result_ids.setdefault(case_group, set())
        started_at = time.perf_counter()
        search_arguments = {
            "query": case["query"],
            "top_k": top_k,
            "district_filter": case.get("district"),
            "domain_filter": case.get("domain"),
            "category_filter": case.get("category"),
            "price_min_filter": case.get("price_min"),
            "price_max_filter": case.get("price_max"),
            "open_at_filter": case.get("open_at"),
            "min_score": threshold,
            "search_modes": search_modes,
        }
        if hasattr(retriever, "search_with_metadata"):
            retrieval_result = retriever.search_with_metadata(
                **search_arguments
            )
            results = retrieval_result.documents
            branch_error_counts.update(retrieval_result.branch_errors)
            branch_result_counts.update(retrieval_result.branch_counts)
            if retrieval_result.exact_shortcut_used:
                exact_shortcut_cases += 1
        else:
            results = retriever.search(**search_arguments)
        latencies_ms.append(
            (time.perf_counter() - started_at) * 1000
        )
        actual_ids = [result.get("parent_id") for result in results]
        usable_ids = {
            str(parent_id)
            for parent_id in actual_ids
            if parent_id not in (None, "")
        }
        returned_parent_ids.update(usable_ids)
        group_result_ids[case_group].update(usable_ids)
        if actual_ids and actual_ids[0] not in (None, ""):
            top_id = str(actual_ids[0])
            top_result_ids.add(top_id)
            group_top_result_ids[case_group].add(top_id)
        expected_ids = set(case.get("expected_parent_ids", []))
        matched_ids = expected_ids.intersection(actual_ids)
        constraints_ok = all(
            matches_case_constraints(result, case)
            for result in results
        )
        min_unique_parent_ids = case.get("min_unique_parent_ids")
        diversity_ok = (
            min_unique_parent_ids is None
            or len(usable_ids) >= min_unique_parent_ids
        )
        if min_unique_parent_ids is not None:
            diversity_cases += 1
            if diversity_ok:
                diversity_passed += 1
        if any(
            case.get(field) is not None
            for field in ("district", "price_min", "price_max", "open_at")
        ):
            constraint_cases += 1
            if constraints_ok:
                constraint_passed += 1

        if not expected_ids:
            success = not actual_ids and constraints_ok and diversity_ok
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
            success = rank is not None and constraints_ok and diversity_ok

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
            group_passed[case_group] += 1
            if rank:
                reciprocal_rank_total += 1 / rank
        else:
            failures.append(
                {
                    "query": case["query"],
                    "expected": sorted(expected_ids),
                    "actual": actual_ids,
                    "constraints_ok": constraints_ok,
                    "diversity_ok": diversity_ok,
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
        "constraint_filter_accuracy": (
            constraint_passed / constraint_cases
            if constraint_cases
            else 1.0
        ),
        "recommendation_diversity_accuracy": (
            diversity_passed / diversity_cases
            if diversity_cases
            else 1.0
        ),
        "group_accuracy": {
            group: {
                "passed": group_passed[group],
                "total": total_count,
                "accuracy": group_passed[group] / total_count,
            }
            for group, total_count in sorted(group_totals.items())
        },
        "diversity": {
            "unique_returned_parent_ids": len(returned_parent_ids),
            "unique_top_result_parent_ids": len(top_result_ids),
            "by_group": {
                group: {
                    "unique_returned_parent_ids": len(
                        group_result_ids[group]
                    ),
                    "unique_top_result_parent_ids": len(
                        group_top_result_ids[group]
                    ),
                }
                for group in sorted(group_totals)
            },
        },
        "latency_ms": {
            "mean": float(np.mean(latencies_ms)),
            "p50": float(np.percentile(latencies_ms, 50)),
            "p95": float(np.percentile(latencies_ms, 95)),
        },
        "estimated_cost_usd": 0.0,
        "search_modes": list(
            search_modes or ("exact", "keyword", "semantic")
        ),
        "retrieval_health": {
            "healthy": not branch_error_counts,
            "branch_errors": dict(branch_error_counts),
            "branch_result_counts": dict(branch_result_counts),
            "exact_shortcut_cases": exact_shortcut_cases,
        },
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
    parser.add_argument(
        "--mode",
        choices=("hybrid", "semantic", "lexical"),
        default="hybrid",
        help="Evaluate hybrid, dense semantic, or offline exact/BM25 search.",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        help="Exit with an error when every healthy report is below this value.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k phải lớn hơn 0")
    if (
        args.min_accuracy is not None
        and not 0 <= args.min_accuracy <= 1
    ):
        parser.error("--min-accuracy phải nằm trong khoảng 0 đến 1")

    retriever = (
        RetrievalEngine.for_lexical_search()
        if args.mode == "lexical"
        else RetrievalEngine()
    )
    try:
        cases = load_cases(args.cases)
        search_modes = {
            "hybrid": ("exact", "keyword", "semantic"),
            "semantic": ("semantic",),
            "lexical": ("exact", "keyword"),
        }[args.mode]
        thresholds = (
            [0.0]
            if args.mode == "lexical"
            else args.thresholds
        )
        reports = [
            evaluate_threshold(
                retriever,
                cases,
                threshold,
                top_k=args.top_k,
                search_modes=search_modes,
            )
            for threshold in thresholds
        ]

        for report in reports:
            print(
                f"threshold={report['threshold']:.2f} "
                f"accuracy={report['accuracy']:.1%} "
                f"recall@{args.top_k}="
                f"{report[f'recall_at_{args.top_k}']:.1%} "
                f"district={report['district_filter_accuracy']:.1%} "
                f"constraints={report['constraint_filter_accuracy']:.1%} "
                f"diversity="
                f"{report['recommendation_diversity_accuracy']:.1%} "
                f"MRR={report['mrr']:.3f} "
                f"p95={report['latency_ms']['p95']:.1f}ms "
                f"healthy={report['retrieval_health']['healthy']} "
                f"({report['passed']}/{report['total']})"
            )
            if report["retrieval_health"]["branch_errors"]:
                print(
                    "  BRANCH_ERRORS: "
                    f"{report['retrieval_health']['branch_errors']}"
                )
            for failure in report["failures"]:
                print(
                    f"  FAIL: {failure['query']} | "
                    f"expected={failure['expected']} | "
                    f"actual={failure['actual']}"
                )

        healthy_reports = [
            report
            for report in reports
            if report["retrieval_health"]["healthy"]
        ]
        if len(healthy_reports) == len(reports):
            best_report = max(
                healthy_reports,
                key=lambda report: (
                    report["accuracy"],
                    report[f"recall_at_{args.top_k}"],
                    report["mrr"],
                ),
            )
            if args.mode == "lexical":
                print("Đánh giá lexical offline hoàn tất.")
            else:
                print(
                    "Ngưỡng đề xuất từ bộ đánh giá hiện tại: "
                    f"{best_report['threshold']:.2f}"
                )
        else:
            print(
                "Không đề xuất threshold vì có retrieval branch bị lỗi. "
                "Hãy kiểm tra Qdrant rồi chạy lại."
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

        if args.min_accuracy is not None:
            best_accuracy = max(
                (
                    report["accuracy"]
                    for report in healthy_reports
                ),
                default=0.0,
            )
            if best_accuracy < args.min_accuracy:
                raise RuntimeError(
                    "Retrieval accuracy "
                    f"{best_accuracy:.1%} is below "
                    f"{args.min_accuracy:.1%}."
                )
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
