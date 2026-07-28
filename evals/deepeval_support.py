from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from core.config import settings
from evals.business_rules import evaluate_business_rules
from evals.common import GoldenCase

try:
    from deepeval.metrics import BaseMetric
    from deepeval.models import DeepEvalBaseLLM
except ImportError as exc:
    raise RuntimeError(
        "Thiếu dependency DeepEval. Chạy: "
        "python -m pip install -r requirements.txt"
    ) from exc


class OpenAICompatibleJudge(DeepEvalBaseLLM):
    """Use the project's OpenAI-compatible endpoint as a DeepEval judge."""

    def __init__(self) -> None:
        client_options = {
            "api_key": settings.GITHUB_TOKEN,
            "base_url": settings.LLM_BASE_URL,
            "timeout": settings.LLM_TIMEOUT_SECONDS,
            "max_retries": settings.EXTERNAL_RETRY_ATTEMPTS - 1,
        }
        self.client = OpenAI(**client_options)
        self.async_client = AsyncOpenAI(**client_options)
        self.model_name = settings.LLM_MODEL

    def load_model(self) -> OpenAI:
        return self.client

    def generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        messages = [{"role": "user", "content": prompt}]
        if schema is not None:
            response = self.client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                response_format=schema,
                temperature=0,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("Judge không trả về structured output.")
            return parsed

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0,
        )
        return response.choices[0].message.content or ""

    async def a_generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        messages = [{"role": "user", "content": prompt}]
        if schema is not None:
            response = await self.async_client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                response_format=schema,
                temperature=0,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("Judge không trả về structured output.")
            return parsed

        response = await self.async_client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0,
        )
        return response.choices[0].message.content or ""

    def get_model_name(self) -> str:
        return self.model_name

    async def aclose(self) -> None:
        await self.async_client.close()
        self.client.close()


class BusinessRulesMetric(BaseMetric):
    """Deterministic DeepEval metric used as a stable CI gate."""

    def __init__(
        self,
        *,
        case: GoldenCase,
        documents: list[dict[str, Any]],
        threshold: float = 0.8,
    ) -> None:
        self.case = case
        self.documents = documents
        self.threshold = threshold
        self.include_reason = True
        self.async_mode = False
        self.strict_mode = False
        self.evaluation_model = "deterministic"

    @property
    def __name__(self) -> str:
        return "Business Rules"

    def measure(self, test_case: Any, *_args, **_kwargs) -> float:
        result = evaluate_business_rules(
            self.case,
            answer=test_case.actual_output,
            documents=self.documents,
            threshold=self.threshold,
        )
        self.score = result.score
        self.success = result.passed
        self.reason = result.reason
        return self.score

    async def a_measure(
        self,
        test_case: Any,
        *_args,
        **_kwargs,
    ) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(getattr(self, "success", False))
