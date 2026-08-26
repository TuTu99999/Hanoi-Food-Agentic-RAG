import json
import re

from pydantic import ValidationError

from automation.policy import decide_replan as decide_replan_policy
from embedding.text_utils import normalize_text
from schemas.agents import OrchestratorDecision
from schemas.automation import ReplanDecision


GREETING_TERMS = {
    "chao",
    "hello",
    "hi",
    "xin chao",
}


def _extract_json_object(value: str) -> dict:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Không tìm thấy JSON object.")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Orchestrator output không phải object.")
    return payload


class OrchestratorAgent:
    def __init__(self, chat_model) -> None:
        self.chat_model = chat_model

    def route(
        self,
        *,
        question: str,
        course_id: str,
        course_version: str,
    ) -> OrchestratorDecision:
        try:
            raw_result = self.chat_model.complete(
                system_prompt=(
                    "Bạn là Orchestrator Agent của trợ lý học tập. Chỉ chọn nhánh, "
                    "không trả lời kiến thức. Chọn knowledge cho câu hỏi cần tra cứu "
                    "môn đang chọn; direct cho lời chào hoặc hỏi khả năng hệ thống; "
                    "unsupported cho yêu cầu ngoài học tập. Trả JSON duy nhất: "
                    '{"route":"knowledge|direct|unsupported","reason":"ngắn gọn"}.'
                ),
                user_prompt=(
                    f"course_id: {course_id}\n"
                    f"course_version: {course_version}\n"
                    f"Yêu cầu: {question}"
                ),
                temperature=0.0,
                max_tokens=200,
            )
            return OrchestratorDecision.model_validate(
                _extract_json_object(raw_result)
            )
        except (
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
            ValidationError,
        ):
            normalized = normalize_text(question)
            if normalized in GREETING_TERMS:
                return OrchestratorDecision(
                    route="direct",
                    reason="Fallback nhận diện lời chào.",
                )
            return OrchestratorDecision(
                route="knowledge",
                reason="Fallback an toàn sang tra cứu có grounding.",
            )

    def decide_replan(
        self,
        *,
        is_correct: bool,
        mastery_after: float,
        has_active_plan: bool,
        has_pending_replan: bool,
    ) -> ReplanDecision:
        """Route a mastery signal without spending an LLM call."""

        return decide_replan_policy(
            is_correct=is_correct,
            mastery_after=mastery_after,
            has_active_plan=has_active_plan,
            has_pending_replan=has_pending_replan,
        )
