import argparse
import asyncio
import json
import re
import unicodedata
from pathlib import Path

import numpy as np

from core.config import settings
from core.resilience import call_with_retry
from rag.Rag import RAGPipeline


DEFAULT_CASES = Path("data/evaluation/rag_cases.json")
JUDGE_INSTRUCTION = (
    "Bạn là bộ chấm faithfulness cho hệ thống RAG. "
    "Chỉ đánh giá câu trả lời có được hỗ trợ bởi context hay không. "
    "Trả về đúng JSON dạng {\"faithfulness\": 0.0}. "
    "Điểm nằm trong khoảng 0 đến 1, không thêm nội dung khác."
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    normalized = normalized.replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def load_cases(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("Bộ câu hỏi RAG phải là danh sách không rỗng.")
    return cases


def correctness_score(answer: str, expected_facts: list[str]) -> float:
    normalized_answer = normalize_text(answer)
    matched = sum(
        normalize_text(fact) in normalized_answer
        for fact in expected_facts
    )
    return matched / len(expected_facts)


def district_filter_score(
    context: list[dict],
    district: str | None,
    expect_no_context: bool,
) -> float | None:
    if not district:
        return None
    if not context:
        return 1.0 if expect_no_context else 0.0

    expected = normalize_text(district)
    return float(
        all(
            normalize_text(document.get("district") or "") == expected
            for document in context
        )
    )


def judge_faithfulness(
    pipeline: RAGPipeline,
    *,
    question: str,
    answer: str,
    context: list[dict],
) -> tuple[float, int, int]:
    judge_input = json.dumps(
        {
            "question": question,
            "answer": answer,
            "context": context,
        },
        ensure_ascii=False,
    )
    response = call_with_retry(
        lambda: pipeline.ai_client.chat.completions.create(
            model=pipeline.llm_model,
            messages=[
                {"role": "system", "content": JUDGE_INSTRUCTION},
                {"role": "user", "content": judge_input},
            ],
            temperature=0,
            max_tokens=80,
        ),
        attempts=settings.EXTERNAL_RETRY_ATTEMPTS,
        base_seconds=settings.EXTERNAL_RETRY_BASE_SECONDS,
        max_seconds=settings.EXTERNAL_RETRY_MAX_SECONDS,
        circuit_breaker=pipeline.llm_circuit_breaker,
    )
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise RuntimeError("LLM judge trả về nội dung không hợp lệ.")

    json_match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not json_match:
        raise RuntimeError("LLM judge không trả về JSON.")
    payload = json.loads(json_match.group(0))
    score = min(1.0, max(0.0, float(payload["faithfulness"])))

    usage = getattr(response, "usage", None)
    return (
        score,
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def evaluate_case(
    pipeline: RAGPipeline,
    case: dict,
    *,
    use_judge: bool,
    input_price_per_million: float,
    output_price_per_million: float,
) -> dict:
    result = pipeline.run_with_metrics(
        user_question=case["question"],
        district=case.get("district"),
    )
    answer = result["answer"]
    context = result["context"]
    prompt_tokens = result["prompt_tokens"]
    completion_tokens = result["completion_tokens"]

    faithfulness = None
    if use_judge:
        (
            faithfulness,
            judge_prompt_tokens,
            judge_completion_tokens,
        ) = judge_faithfulness(
            pipeline,
            question=case["question"],
            answer=answer,
            context=context,
        )
        prompt_tokens += judge_prompt_tokens
        completion_tokens += judge_completion_tokens

    estimated_cost = (
        prompt_tokens * input_price_per_million
        + completion_tokens * output_price_per_million
    ) / 1_000_000
    return {
        "id": case["id"],
        "correctness": correctness_score(
            answer,
            case["expected_facts"],
        ),
        "faithfulness": faithfulness,
        "district_filter": district_filter_score(
            context,
            case.get("district"),
            case.get("expect_no_context", False),
        ),
        "latency_ms": result["latency_ms"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": estimated_cost,
        "answer": answer,
    }


def build_summary(results: list[dict]) -> dict:
    faithfulness = [
        result["faithfulness"]
        for result in results
        if result["faithfulness"] is not None
    ]
    district_scores = [
        result["district_filter"]
        for result in results
        if result["district_filter"] is not None
    ]
    latencies = [result["latency_ms"] for result in results]
    return {
        "cases": len(results),
        "correctness": float(
            np.mean([result["correctness"] for result in results])
        ),
        "faithfulness": (
            float(np.mean(faithfulness)) if faithfulness else None
        ),
        "district_filter_accuracy": (
            float(np.mean(district_scores))
            if district_scores
            else None
        ),
        "latency_ms": {
            "mean": float(np.mean(latencies)),
            "p50": float(np.percentile(latencies, 50)),
            "p95": float(np.percentile(latencies, 95)),
        },
        "prompt_tokens": sum(
            result["prompt_tokens"] for result in results
        ),
        "completion_tokens": sum(
            result["completion_tokens"] for result in results
        ),
        "estimated_cost_usd": sum(
            result["estimated_cost_usd"] for result in results
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Đánh giá correctness, faithfulness, filter, latency và cost.",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--skip-faithfulness-judge",
        action="store_true",
        help="Không gọi thêm LLM judge để tiết kiệm token.",
    )
    parser.add_argument(
        "--input-price-per-million",
        type=float,
        default=0,
    )
    parser.add_argument(
        "--output-price-per-million",
        type=float,
        default=0,
    )
    args = parser.parse_args()

    pipeline = RAGPipeline()
    try:
        pipeline.warmup()
        results = [
            evaluate_case(
                pipeline,
                case,
                use_judge=not args.skip_faithfulness_judge,
                input_price_per_million=args.input_price_per_million,
                output_price_per_million=args.output_price_per_million,
            )
            for case in load_cases(args.cases)
        ]
        report = {
            "model": settings.LLM_MODEL,
            "summary": build_summary(results),
            "results": results,
        }
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
    finally:
        asyncio.run(pipeline.aclose())


if __name__ == "__main__":
    main()
