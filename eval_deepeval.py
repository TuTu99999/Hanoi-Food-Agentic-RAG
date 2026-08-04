from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from core.config import settings
from evals.common import (
    DEFAULT_CONVERSATION_CASES,
    DEFAULT_RAG_CASES,
    GoldenCase,
    collect_conversation_record,
    collect_record,
    evaluation_metadata,
    load_conversation_cases,
    load_cases,
    mean,
    save_report,
)
from rag.Rag import RAGPipeline


def _load_deepeval():
    try:
        from deepeval.metrics import ConversationalGEval, GEval
        from deepeval.test_case import (
            ConversationalTestCase,
            LLMTestCase,
            MultiTurnParams,
            SingleTurnParams,
            Turn,
        )
        from evals.deepeval_support import (
            BusinessRulesMetric,
            OpenAICompatibleJudge,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu dependency DeepEval. Chạy: "
            "python -m pip install -r requirements.txt"
        ) from exc

    return {
        "GEval": GEval,
        "ConversationalGEval": ConversationalGEval,
        "ConversationalTestCase": ConversationalTestCase,
        "LLMTestCase": LLMTestCase,
        "MultiTurnParams": MultiTurnParams,
        "SingleTurnParams": SingleTurnParams,
        "Turn": Turn,
        "BusinessRulesMetric": BusinessRulesMetric,
        "OpenAICompatibleJudge": OpenAICompatibleJudge,
    }


def _to_case(record: dict[str, Any]) -> GoldenCase:
    payload = record["case"]
    return GoldenCase(
        id=payload["id"],
        question=payload["question"],
        expected_facts=tuple(payload["expected_facts"]),
        reference=payload["reference"],
        district=payload.get("district"),
        expect_no_context=payload.get("expect_no_context", False),
    )


def _build_judge_metric(deepeval: dict[str, Any], judge: Any, threshold: float):
    params = deepeval["SingleTurnParams"]
    return deepeval["GEval"](
        name="Food RAG constraint adherence",
        evaluation_steps=[
            (
                "Compare the actual output with the expected output and "
                "penalize contradictions or missing required facts."
            ),
            (
                "Verify that every factual recommendation is supported by "
                "the retrieval context; heavily penalize invented venues."
            ),
            (
                "Verify explicit district and budget requirements are treated "
                "as hard constraints and are never silently relaxed."
            ),
            (
                "When retrieval context is empty, reward a concise honest "
                "refusal and penalize any fabricated recommendation."
            ),
        ],
        evaluation_params=[
            params.INPUT,
            params.ACTUAL_OUTPUT,
            params.EXPECTED_OUTPUT,
            params.RETRIEVAL_CONTEXT,
        ],
        threshold=threshold,
        model=judge,
        async_mode=False,
    )


def evaluate_records(
    records: list[dict[str, Any]],
    *,
    use_judge: bool,
    deterministic_threshold: float,
    judge_threshold: float,
) -> tuple[list[dict[str, Any]], Any | None]:
    deepeval = _load_deepeval()
    judge = (
        deepeval["OpenAICompatibleJudge"]()
        if use_judge
        else None
    )
    judge_metric = (
        _build_judge_metric(deepeval, judge, judge_threshold)
        if judge is not None
        else None
    )
    results = []

    for record in records:
        test_case = deepeval["LLMTestCase"](
            input=record["user_input"],
            actual_output=record["response"],
            expected_output=record["expected_output"],
            retrieval_context=record["retrieved_contexts"],
        )
        business_metric = deepeval["BusinessRulesMetric"](
            case=_to_case(record),
            documents=record["context_documents"],
            threshold=deterministic_threshold,
        )
        business_metric.measure(test_case)

        item = {
            "id": record["case"]["id"],
            "business_rules": {
                "score": float(business_metric.score),
                "passed": business_metric.is_successful(),
                "reason": business_metric.reason,
            },
            "judge": None,
        }
        if judge_metric is not None:
            judge_metric.measure(test_case)
            item["judge"] = {
                "score": float(judge_metric.score),
                "passed": judge_metric.is_successful(),
                "reason": judge_metric.reason,
            }
        results.append(item)

    return results, judge


def evaluate_conversations(
    records: list[dict[str, Any]],
    *,
    deepeval: dict[str, Any],
    judge: Any,
    threshold: float,
) -> list[dict[str, Any]]:
    params = deepeval["MultiTurnParams"]
    metric = deepeval["ConversationalGEval"](
        name="Multi-turn food assistant behavior",
        evaluation_steps=[
            (
                "Read the whole conversation and identify the food, district, "
                "budget direction, and other constraints established by the user."
            ),
            (
                "Verify each assistant response follows the latest user intent "
                "while retaining constraints that were not explicitly changed, "
                "and drops constraints the user explicitly clears."
            ),
            (
                "When the user reverses a constraint such as 'đổ về' to "
                "'đổ lên', verify the assistant applies the new direction "
                "instead of fabricating or keeping the old constraint."
            ),
            (
                "When the user switches district or topic, verify the old hard "
                "filter is not carried into the new request."
            ),
            (
                "For ambiguous or compared venues, verify fields from different "
                "entities are never mixed and clarification is requested when "
                "the available evidence cannot identify one venue."
            ),
            (
                "Verify factual recommendations are supported by the retrieval "
                "context attached to the corresponding assistant turn; empty "
                "context must lead to an honest no-answer."
            ),
        ],
        evaluation_params=[
            params.CONTENT,
            params.RETRIEVAL_CONTEXT,
        ],
        threshold=threshold,
        model=judge,
        async_mode=False,
    )
    results = []

    for record in records:
        turns = []
        for turn in record["turns"]:
            turns.append(
                deepeval["Turn"](
                    role="user",
                    content=turn["user_input"],
                )
            )
            turns.append(
                deepeval["Turn"](
                    role="assistant",
                    content=turn["response"],
                    retrieval_context=turn["retrieved_contexts"],
                )
            )

        test_case = deepeval["ConversationalTestCase"](
            scenario=record["scenario"],
            expected_outcome=record["expected_outcome"],
            turns=turns,
        )
        metric.measure(test_case)
        results.append(
            {
                "id": record["id"],
                "score": float(metric.score),
                "passed": metric.is_successful(),
                "reason": metric.reason,
            }
        )

    return results


def build_summary(
    results: list[dict[str, Any]],
    conversation_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    judge_results = [
        item["judge"]
        for item in results
        if item["judge"] is not None
    ]
    conversations = conversation_results or []
    return {
        "cases": len(results),
        "business_rules": {
            "mean": mean(
                item["business_rules"]["score"]
                for item in results
            ),
            "passed": sum(
                item["business_rules"]["passed"]
                for item in results
            ),
        },
        "judge": {
            "mean": mean(item["score"] for item in judge_results),
            "passed": sum(item["passed"] for item in judge_results),
            "evaluated": len(judge_results),
        },
        "conversations": {
            "mean": mean(item["score"] for item in conversations),
            "passed": sum(item["passed"] for item in conversations),
            "evaluated": len(conversations),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run DeepEval business-rule regression and optional G-Eval judge."
        ),
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_RAG_CASES)
    parser.add_argument(
        "--conversation-cases",
        type=Path,
        default=DEFAULT_CONVERSATION_CASES,
    )
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--skip-conversations", action="store_true")
    parser.add_argument(
        "--deterministic-threshold",
        type=float,
        default=0.8,
    )
    parser.add_argument("--judge-threshold", type=float, default=0.7)
    args = parser.parse_args()

    for name in ("deterministic_threshold", "judge_threshold"):
        value = getattr(args, name)
        if not 0 <= value <= 1:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 1")
    return args


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    pipeline = RAGPipeline()
    judge = None
    try:
        pipeline.warmup()
        records = [
            collect_record(pipeline, case)
            for case in load_cases(args.cases, max_cases=args.max_cases)
        ]
        results, judge = evaluate_records(
            records,
            use_judge=not args.skip_judge,
            deterministic_threshold=args.deterministic_threshold,
            judge_threshold=args.judge_threshold,
        )
        conversation_results = []
        if judge is not None and not args.skip_conversations:
            deepeval = _load_deepeval()
            conversation_records = [
                collect_conversation_record(pipeline, case)
                for case in load_conversation_cases(
                    args.conversation_cases
                )
            ]
            conversation_results = evaluate_conversations(
                conversation_records,
                deepeval=deepeval,
                judge=judge,
                threshold=args.judge_threshold,
            )

        summary = build_summary(results, conversation_results)
        report = {
            "framework": "deepeval",
            "framework_version": "4.1.4",
            "judge_model": (
                settings.LLM_MODEL if not args.skip_judge else None
            ),
            "metadata": evaluation_metadata(
                cases_path=args.cases,
                collection=settings.QDRANT_COLLECTION,
                embedding_model=settings.EMBEDDING_MODEL,
            ),
            "summary": summary,
            "results": results,
            "conversation_results": conversation_results,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        save_report(args.output, report)

        failed_business = (
            summary["business_rules"]["passed"] < summary["cases"]
        )
        failed_judge = (
            not args.skip_judge
            and (
                summary["judge"]["evaluated"] == 0
                or summary["judge"]["mean"] is None
                or summary["judge"]["mean"] < args.judge_threshold
            )
        )
        failed_conversations = (
            not args.skip_judge
            and not args.skip_conversations
            and (
                summary["conversations"]["evaluated"] == 0
                or summary["conversations"]["mean"] is None
                or summary["conversations"]["mean"]
                < args.judge_threshold
            )
        )
        if failed_business or failed_judge or failed_conversations:
            raise SystemExit("DeepEval regression threshold failed.")
    finally:
        if judge is not None:
            asyncio.run(judge.aclose())
        asyncio.run(pipeline.aclose())


if __name__ == "__main__":
    main()
