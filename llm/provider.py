from dataclasses import dataclass
from typing import Any, Callable

from openai import AsyncOpenAI, OpenAI


SUPPORTED_PROVIDERS = {"gemini", "kimi"}


@dataclass(frozen=True)
class LLMProviderConfig:
    """Cấu hình tối thiểu dùng chung cho Gemini và Kimi."""

    provider: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError("provider chỉ hỗ trợ gemini hoặc kimi")
        if not self.api_key:
            raise ValueError("api_key không được để trống")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url phải là HTTP(S) URL")
        if not self.model:
            raise ValueError("model không được để trống")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds phải lớn hơn 0")


def provider_config_from_settings(settings: Any) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=settings.LLM_PROVIDER,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )


class OpenAICompatibleProvider:
    """Một adapter nhỏ để phần agent không phụ thuộc trực tiếp Gemini/Kimi."""

    def __init__(
        self,
        config: LLMProviderConfig,
        *,
        sync_client_factory: Callable[..., Any] = OpenAI,
        async_client_factory: Callable[..., Any] = AsyncOpenAI,
        client_wrapper: Callable[[Any], Any] | None = None,
    ) -> None:
        self.config = config
        client_options = {
            "base_url": config.base_url,
            "api_key": config.api_key,
            "timeout": config.timeout_seconds,
            "max_retries": 0,
        }
        wrapper = client_wrapper or (lambda client: client)
        self.sync_client = wrapper(sync_client_factory(**client_options))
        self.async_client = wrapper(async_client_factory(**client_options))

    @property
    def name(self) -> str:
        return self.config.provider

    @property
    def model(self) -> str:
        return self.config.model

    async def aclose(self) -> None:
        await self.async_client.close()
        self.sync_client.close()
