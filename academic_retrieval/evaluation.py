import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from schemas.indexing import (
    AcademicRetrievalCase,
    AcademicRetrievalEvaluationReport,
    AcademicRetrievalHit,
)


def load_retrieval_cases(path: str | Path) -> list[AcademicRetrievalCase]:
    resolved_path = Path(path).resolve()
    try:
        with resolved_path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Không thể đọc retrieval cases: {resolved_path}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("Retrieval cases phải là một danh sách không rỗng.")
    try:
        cases = [AcademicRetrievalCase.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise ValueError(f"Retrieval case không đúng schema: {exc}") from exc
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id trong retrieval cases phải duy nhất.")
    return cases


def _citation_is_complete(hit: AcademicRetrievalHit) -> bool:
    citation = hit.citation
    has_locator = any(
        value is not None
        for value in (
            citation.page_number,
            citation.start_line,
            citation.start_paragraph,
        )
    )
    return bool(
        citation.document_id
        and citation.document_title
        and citation.source_path
        and has_locator
    )


def evaluate_academic_retrieval(
    retriever: Any,
    cases: list[AcademicRetrievalCase],
    *,
    modes: tuple[str, ...] = ("dense", "keyword"),
) -> AcademicRetrievalEvaluationReport:
    if not cases:
        raise ValueError("Cần ít nhất một retrieval case để đánh giá.")

    hit_count = 0
    recall_total = 0.0
    reciprocal_rank_total = 0.0
    citation_complete_count = 0
    retrieved_hit_count = 0
    cross_course_leakage_count = 0
    empty_result_count = 0
    case_results = []

    for case in cases:
        result = retriever.search(
            case.query,
            course_id=case.course_id,
            course_version=case.course_version,
            top_k=case.top_k,
            modes=modes,
        )
        returned_ids = [hit.chunk_id for hit in result.hits]
        expected_ids = set(case.expected_chunk_ids)
        relevant_ids = expected_ids.intersection(returned_ids)
        recall = len(relevant_ids) / len(expected_ids)
        first_relevant_rank = next(
            (
                rank
                for rank, chunk_id in enumerate(returned_ids, start=1)
                if chunk_id in expected_ids
            ),
            None,
        )
        reciprocal_rank = (
            1.0 / first_relevant_rank
            if first_relevant_rank is not None
            else 0.0
        )

        hit_count += int(bool(relevant_ids))
        recall_total += recall
        reciprocal_rank_total += reciprocal_rank
        empty_result_count += int(not result.hits)
        for hit in result.hits:
            retrieved_hit_count += 1
            citation_complete_count += int(_citation_is_complete(hit))
            cross_course_leakage_count += int(hit.course_id != case.course_id)

        case_results.append(
            {
                "case_id": case.case_id,
                "returned_chunk_ids": returned_ids,
                "relevant_chunk_ids": sorted(relevant_ids),
                "recall": round(recall, 6),
                "reciprocal_rank": round(reciprocal_rank, 6),
            }
        )

    case_count = len(cases)
    return AcademicRetrievalEvaluationReport(
        case_count=case_count,
        hit_rate_at_k=round(hit_count / case_count, 6),
        recall_at_k=round(recall_total / case_count, 6),
        mean_reciprocal_rank=round(
            reciprocal_rank_total / case_count,
            6,
        ),
        citation_completeness=round(
            citation_complete_count / retrieved_hit_count,
            6,
        )
        if retrieved_hit_count
        else 0.0,
        cross_course_leakage_count=cross_course_leakage_count,
        empty_result_count=empty_result_count,
        cases=case_results,
    )
