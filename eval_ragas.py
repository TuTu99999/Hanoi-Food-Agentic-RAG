from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from openai import AsyncOpenAI

from core.config import settings
from evals.common import (
    DEFAULT_RAG_CASES,
    collect_record,
    evaluation_metadata,
    failed_ragas_metrics,
    load_cases,
    mean,
    save_report,
)
from rag.Rag import RAGPipeline


def _load_ragas():
    try:
        from ragas.embeddings import HuggingFaceEmbeddings
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu dependency Ragas. Chạy: "
            "python -m pip install -r requirements.txt"
        ) from exc

    return {
        "HuggingFaceEmbeddings": HuggingFaceEmbeddings,
        "llm_factory": llm_factory,
        "AnswerRelevancy": AnswerRelevancy,
        "ContextPrecision": ContextPrecision,
        "ContextRecall": ContextRecall,
        "Faithfulness": Faithfulness,
    }


def _metric_payload(result: Any) -> dict[str, Any]:
    value = getattr(result, "value", result)
    reason = getattr(result, "reason", None)
    return {
        "score": float(value),
        "reason": str(reason) if reason else None,
    }


async def _score_record(
    record: dict[str, Any],
    scorers: dict[str, Any],
) -> dict[str, Any]:
    contexts = record["retrieved_contexts"]
    if not contexts:
        return {
            "id": record["case"]["id"],
            "skipped": True,
            "skip_reason": (
                "Ragas context metrics require retrieved evidence; "
                "the deterministic suite owns empty-context behavior."
            ),
            "metrics": {},
        }

    common = {
        "user_input": record["user_input"],
        "response": record["response"],
        "retrieved_contexts": contexts,
    }
    calls = {
        "faithfulness": scorers["faithfulness"].ascore(**common),
        "context_precision": scorers["context_precision"].ascore(
            user_input=record["user_input"],
            reference=record["reference"],
            retrieved_contexts=contexts,
        ),
        "context_recall": scorers["context_recall"].ascore(
            user_input=record["user_input"],
            reference=record["reference"],
            retrieved_contexts=contexts,
        ),
        "answer_relevancy": scorers["answer_relevancy"].ascore(
            user_input=record["user_input"],
            response=record["response"],
        ),
    }
    results = await asyncio.gather(*calls.values())
    return {
        "id": record["case"]["id"],
        "skipped": False,
        "metrics": {
            name: _metric_payload(result)
            for name, result in zip(calls, results)
        },
    }


async def evaluate(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ragas = _load_ragas()
    client = AsyncOpenAI(
        api_key=settings.GITHUB_TOKEN,
        base_url=settings.LLM_BASE_URL,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.EXTERNAL_RETRY_ATTEMPTS - 1,
    )
    try:
        llm = ragas["llm_factory"](
            settings.LLM_MODEL,
            provider="openai",
            client=client,
            temperature=0,
        )
        embeddings = ragas["HuggingFaceEmbeddings"](
            model=settings.EMBEDDING_MODEL,
            device="cpu",
            local_files_only=settings.EMBEDDING_LOCAL_FILES_ONLY,
        )
        scorers = {
            "faithfulness": ragas["Faithfulness"](llm=llm),
            "context_precision": ragas["ContextPrecision"](llm=llm),
            "context_recall": ragas["ContextRecall"](llm=llm),
            "answer_relevancy": ragas["AnswerRelevancy"](
                llm=llm,
                embeddings=embeddings,
            ),
        }

        results = []
        for record in records:
            results.append(await _score_record(record, scorers))
        return results
    finally:
        await client.close()


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = (
        "faithfulness",
        "context_precision",
        "context_recall",
        "answer_relevancy",
    )
    return {
        "evaluated_cases": sum(not item["skipped"] for item in results),
        "skipped_cases": sum(item["skipped"] for item in results),
        "metrics": {
            metric_name: mean(
                item["metrics"].get(metric_name, {}).get("score")
                for item in results
            )
            for metric_name in metric_names
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real Ragas metrics against the live RAG pipeline.",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_RAG_CASES)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--min-score",
        type=float,
        help="Fail when any aggregate Ragas metric is below this value.",
    )
    args = parser.parse_args()
    if args.min_score is not None and not 0 <= args.min_score <= 1:
        parser.error("--min-score must be between 0 and 1")
    return args


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    pipeline = RAGPipeline()
    try:
        pipeline.warmup()
        records = [
            collect_record(pipeline, case)
            for case in load_cases(args.cases, max_cases=args.max_cases)
        ]
        results = asyncio.run(evaluate(records))
        summary = build_summary(results)
        report = {
            "framework": "ragas",
            "framework_version": "0.4.3",
            "judge_model": settings.LLM_MODEL,
            "metadata": evaluation_metadata(
                cases_path=args.cases,
                collection=settings.QDRANT_COLLECTION,
                embedding_model=settings.EMBEDDING_MODEL,
            ),
            "summary": summary,
            "results": results,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        save_report(args.output, report)

        failed = failed_ragas_metrics(summary, args.min_score)
        if failed:
            raise SystemExit(
                "Ragas metrics below threshold: " + ", ".join(failed)
            )
    finally:
        asyncio.run(pipeline.aclose())


if __name__ == "__main__":
    main()
