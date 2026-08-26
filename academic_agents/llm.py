from typing import Any, Protocol


class AcademicChatModel(Protocol):
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str: ...


class OpenAICompatibleChatModel:
    """Small chat adapter shared by Kimi and Gemini providers."""

    def __init__(
        self,
        provider: Any,
        *,
        max_output_tokens: int = 800,
        reasoning_effort: str | None = None,
    ) -> None:
        self.provider = provider
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        options = {
            "model": self.provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_output_tokens,
        }
        if self.reasoning_effort:
            options["reasoning_effort"] = self.reasoning_effort
        response = self.provider.sync_client.chat.completions.create(**options)
        choices = getattr(response, "choices", None) or []
        content = (
            getattr(getattr(choices[0], "message", None), "content", None)
            if choices
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM không trả về nội dung hợp lệ.")
        return content.strip()
