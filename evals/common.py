from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from embedding.text_utils import normalize_text


DEFAULT_RAG_CASES = Path("data/evaluation/rag_cases.json")
DEFAULT_CONVERSATION_CASES = Path(
    "data/evaluation/conversation_cases.json"
)
CONTEXT_FIELDS = (
    "parent_id",
    "title",
    "address",
    "district",
    "category",
    "price_range",
    "price_min",
    "price_max",
    "opening_hours",
    "content",
)


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    expected_facts: tuple[str, ...]
    reference: str
    district: str | None = None
    expect_no_context: bool = False


@dataclass(frozen=True)
class ConversationTurn:
    user_input: str
    district: str | None = None


@dataclass(frozen=True)
class ConversationCase:
    id: str
    scenario: str
    expected_outcome: str
    turns: tuple[ConversationTurn, ...]


def _require_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Case evaluation thiếu trường text '{field}'.")
    return value.strip()


def parse_case(payload: dict[str, Any]) -> GoldenCase:
    if not isinstance(payload, dict):
        raise ValueError("Mỗi case evaluation phải là một object.")

    expected_facts = payload.get("expected_facts")
    if (
        not isinstance(expected_facts, list)
        or not expected_facts
        or not all(
            isinstance(fact, str) and fact.strip()
            for fact in expected_facts
        )
    ):
        raise ValueError("expected_facts phải là danh sách text không rỗng.")

    reference = payload.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        reference = "Thông tin bắt buộc: " + "; ".join(expected_facts)

    district = payload.get("district")
    if district is not None and (
        not isinstance(district, str) or not district.strip()
    ):
        raise ValueError("district phải là text hoặc null.")

    return GoldenCase(
        id=_require_text(payload, "id"),
        question=_require_text(payload, "question"),
        expected_facts=tuple(fact.strip() for fact in expected_facts),
        reference=reference.strip(),
        district=district.strip() if district else None,
        expect_no_context=bool(payload.get("expect_no_context", False)),
    )


def load_cases(
    path: Path = DEFAULT_RAG_CASES,
    *,
    max_cases: int | None = None,
) -> list[GoldenCase]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, list) or not payload:
        raise ValueError("Bộ evaluation phải là danh sách không rỗng.")
    if max_cases is not None and max_cases <= 0:
        raise ValueError("max_cases phải lớn hơn 0.")

    cases = [parse_case(item) for item in payload]
    return cases[:max_cases] if max_cases is not None else cases


def parse_conversation_case(
    payload: dict[str, Any],
) -> ConversationCase:
    if not isinstance(payload, dict):
        raise ValueError("Mỗi conversation case phải là một object.")

    raw_turns = payload.get("turns")
    if not isinstance(raw_turns, list) or len(raw_turns) < 2:
        raise ValueError(
            "Conversation case phải có ít nhất hai user turns."
        )

    turns = []
    for raw_turn in raw_turns:
        if not isinstance(raw_turn, dict):
            raise ValueError("Mỗi conversation turn phải là một object.")
        district = raw_turn.get("district")
        if district is not None and (
            not isinstance(district, str) or not district.strip()
        ):
            raise ValueError("district của conversation turn không hợp lệ.")
        turns.append(
            ConversationTurn(
                user_input=_require_text(raw_turn, "user_input"),
                district=district.strip() if district else None,
            )
        )

    return ConversationCase(
        id=_require_text(payload, "id"),
        scenario=_require_text(payload, "scenario"),
        expected_outcome=_require_text(payload, "expected_outcome"),
        turns=tuple(turns),
    )


def load_conversation_cases(
    path: Path = DEFAULT_CONVERSATION_CASES,
) -> list[ConversationCase]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list) or not payload:
        raise ValueError(
            "Bộ conversation evaluation phải là danh sách không rỗng."
        )
    return [parse_conversation_case(item) for item in payload]


def select_context_fields(document: dict[str, Any]) -> dict[str, Any]:
    return {
        field: document.get(field)
        for field in CONTEXT_FIELDS
        if document.get(field) not in (None, "", [])
    }


def context_to_text(document: dict[str, Any]) -> str:
    return json.dumps(
        select_context_fields(document),
        ensure_ascii=False,
        sort_keys=True,
    )


def expected_output(case: GoldenCase) -> str:
    constraints = [case.reference]
    if case.district:
        constraints.append(
            f"Điều kiện cứng: chỉ dùng kết quả thuộc quận {case.district}."
        )
    if case.expect_no_context:
        constraints.append(
            "Không có bằng chứng phù hợp: phải từ chối ngắn gọn và không bịa quán."
        )
    return "\n".join(constraints)


def fact_coverage(answer: str, expected_facts: Iterable[str]) -> float:
    facts = tuple(expected_facts)
    if not facts:
        return 1.0

    normalized_answer = normalize_text(answer)
    matched = sum(
        normalize_text(fact) in normalized_answer
        for fact in facts
    )
    return matched / len(facts)


def district_filter_score(
    documents: list[dict[str, Any]],
    expected_district: str | None,
    *,
    expect_no_context: bool,
) -> float | None:
    if not expected_district:
        return None
    if not documents:
        return 1.0 if expect_no_context else 0.0

    normalized_district = normalize_text(expected_district)
    return float(
        all(
            normalize_text(str(document.get("district") or ""))
            == normalized_district
            for document in documents
        )
    )


def deterministic_scores(
    case: GoldenCase,
    *,
    answer: str,
    documents: list[dict[str, Any]],
) -> dict[str, float | None]:
    no_context_score = None
    if case.expect_no_context:
        no_context_score = float(not documents)

    return {
        "fact_coverage": fact_coverage(answer, case.expected_facts),
        "district_filter": district_filter_score(
            documents,
            case.district,
            expect_no_context=case.expect_no_context,
        ),
        "no_context": no_context_score,
    }


def collect_record(pipeline: Any, case: GoldenCase) -> dict[str, Any]:
    result = pipeline.run_with_metrics(
        user_question=case.question,
        district=case.district,
    )
    documents = result.get("context") or []
    if not isinstance(documents, list):
        raise RuntimeError("RAG pipeline trả về context không hợp lệ.")

    answer = result.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("RAG pipeline trả về answer rỗng.")

    return {
        "case": asdict(case),
        "user_input": case.question,
        "response": answer,
        "reference": case.reference,
        "retrieved_contexts": [
            context_to_text(document)
            for document in documents
        ],
        "context_documents": [
            select_context_fields(document)
            for document in documents
        ],
        "expected_output": expected_output(case),
        "latency_ms": float(result.get("latency_ms", 0) or 0),
        "prompt_tokens": int(result.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(
            result.get("completion_tokens", 0) or 0
        ),
        "deterministic": deterministic_scores(
            case,
            answer=answer,
            documents=documents,
        ),
    }


def collect_conversation_record(
    pipeline: Any,
    case: ConversationCase,
) -> dict[str, Any]:
    history: list[dict[str, str]] = []
    turns = []

    for turn in case.turns:
        result = pipeline.run_with_metrics(
            user_question=turn.user_input,
            district=turn.district,
            history=history,
        )
        answer = result.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("RAG pipeline trả về answer hội thoại rỗng.")

        documents = result.get("context") or []
        if not isinstance(documents, list):
            raise RuntimeError("RAG pipeline trả về context không hợp lệ.")

        turns.append(
            {
                "user_input": turn.user_input,
                "response": answer,
                "retrieved_contexts": [
                    context_to_text(document)
                    for document in documents
                ],
            }
        )
        history.extend(
            [
                {"role": "user", "content": turn.user_input},
                {"role": "assistant", "content": answer},
            ]
        )

    return {
        "id": case.id,
        "scenario": case.scenario,
        "expected_outcome": case.expected_outcome,
        "turns": turns,
    }


def mean(values: Iterable[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def failed_ragas_metrics(
    summary: dict[str, Any],
    minimum_score: float | None,
) -> list[str]:
    failed = []
    if summary["evaluated_cases"] == 0:
        failed.append("evaluated_cases")
    if minimum_score is None:
        return failed
    failed.extend(
        name
        for name, value in summary["metrics"].items()
        if value is None or value < minimum_score
    )
    return failed


def save_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)


def evaluation_metadata(
    *,
    cases_path: Path,
    collection: str,
    embedding_model: str,
) -> dict[str, str | None]:
    return {
        "source_sha": (
            os.getenv("EVALUATION_SOURCE_SHA")
            or os.getenv("GITHUB_SHA")
            or None
        ),
        "collection": collection,
        "embedding_model": embedding_model,
        "dataset_sha256": hashlib.sha256(
            cases_path.read_bytes()
        ).hexdigest(),
    }
