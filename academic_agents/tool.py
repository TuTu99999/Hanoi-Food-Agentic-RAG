from collections.abc import Callable
from typing import Any

from schemas.agents import (
    AcademicKnowledgeSearchInput,
    AcademicKnowledgeSearchOutput,
)


class AcademicRetrievalTool:
    name = "search_course_knowledge"
    description = (
        "Tìm evidence có citation trong đúng course_id và course_version."
    )

    def __init__(
        self,
        retriever_resolver: Callable[[str, str], Any],
    ) -> None:
        self.retriever_resolver = retriever_resolver

    def run(
        self,
        tool_input: AcademicKnowledgeSearchInput,
    ) -> AcademicKnowledgeSearchOutput:
        retriever = self.retriever_resolver(
            tool_input.course_id,
            tool_input.course_version,
        )
        result = retriever.search(
            tool_input.query,
            course_id=tool_input.course_id,
            course_version=tool_input.course_version,
            top_k=tool_input.top_k,
        )
        if (
            result.course_id != tool_input.course_id
            or result.course_version != tool_input.course_version
        ):
            raise RuntimeError("Academic retrieval tool trả dữ liệu sai scope.")
        return AcademicKnowledgeSearchOutput(result=result)
