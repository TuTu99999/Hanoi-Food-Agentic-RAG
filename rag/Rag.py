import asyncio
import json
import logging
import threading
import time
from typing import AsyncIterator

from openai import AsyncOpenAI, OpenAI

from core.config import settings
from core.resilience import (
    CircuitBreaker,
    call_with_retry,
    call_with_retry_async,
)
from embedding.text_utils import normalize_text


logger = logging.getLogger(__name__)

NO_RESULTS_MESSAGE = (
    "Dựa trên dữ liệu hiện tại, hệ thống không tìm thấy thông tin nào "
    "liên quan đến câu hỏi của bạn."
)
SYSTEM_INSTRUCTION = (
    "Bạn là trợ lý tư vấn ẩm thực Hà Nội.\n"
    "Hãy trả lời tự nhiên, thân thiện và hữu ích.\n"
    "QUY TẮC CHỐNG ẢO TƯỞNG:\n"
    "1. Chỉ dùng dữ liệu trong phần 'NGỮ CẢNH CUNG CẤP' của câu hỏi hiện tại.\n"
    "2. Lịch sử hội thoại chỉ dùng để hiểu người dùng đang nhắc đến đối tượng nào; "
    "không coi lịch sử là nguồn dữ liệu mới.\n"
    "3. Không tự thêm, suy đoán hoặc dùng kiến thức bên ngoài.\n"
    "4. Nếu ngữ cảnh không đủ, hãy trả lời: "
    "'Dựa trên dữ liệu hiện tại, tôi không có đủ thông tin chi tiết về vấn đề này.'\n"
    "5. Có thể nhận biết lỗi chính tả nhỏ khi tên trong ngữ cảnh khớp rõ ràng; "
    "không tự tạo địa điểm mới.\n"
    "6. Dữ liệu giờ mở cửa có nhãn 'daily_assumed' chỉ là lịch hằng ngày từ "
    "nguồn hiện có; không tự khẳng định lịch ngày lễ hoặc ngày đặc biệt."
)


class RAGConfigurationError(RuntimeError):
    pass


def _greeting_response(question: str) -> str | None:
    greetings = {
        "chao",
        "chao ban",
        "hello",
        "hey",
        "hi",
        "xin chao",
    }
    if normalize_text(question) not in greetings:
        return None
    return (
        "Xin chào! Mình có thể giúp bạn tìm quán ăn, món ăn, "
        "địa chỉ, giá và giờ mở cửa tại Hà Nội."
    )


class RAGPipeline:
    def __init__(self):
        """
        Khởi tạo RAG Pipeline dùng OpenAI-compatible API:
        1. Kiểm tra GITHUB_TOKEN trong .env.
        2. Khởi tạo client từ LLM_BASE_URL và LLM_MODEL.
        3. Khởi tạo lazy loading cho RetrievalEngine.
        """
        github_token = settings.GITHUB_TOKEN
        if not github_token:
            raise RAGConfigurationError(
                "Không tìm thấy GITHUB_TOKEN trong file .env hoặc hệ thống."
            )

        self.retriever = None
        self._retriever_lock = threading.Lock()
        self.agentic_workflow = None
        self._agentic_workflow_lock = threading.Lock()

        client_options = {
            "base_url": settings.LLM_BASE_URL,
            "api_key": github_token,
            "timeout": settings.LLM_TIMEOUT_SECONDS,
            "max_retries": 0,
        }
        self.ai_client = OpenAI(**client_options)
        self.async_ai_client = AsyncOpenAI(**client_options)
        self.llm_model = settings.LLM_MODEL
        self.llm_circuit_breaker = CircuitBreaker(
            failure_threshold=settings.CIRCUIT_BREAKER_FAILURES,
            reset_seconds=settings.CIRCUIT_BREAKER_RESET_SECONDS,
        )

    def _get_retriever(self):
        """Hàm Lazy Load RetrievalEngine"""
        if self.retriever is None:
            with self._retriever_lock:
                if self.retriever is None:
                    logger.info(
                        "Loading retrieval engine and embedding model."
                    )
                    from embedding.retrieval_engine import RetrievalEngine

                    self.retriever = RetrievalEngine(
                        qdrant_url=settings.QDRANT_URL,
                        qdrant_api_key=settings.QDRANT_API_KEY,
                        collection_name=settings.QDRANT_COLLECTION,
                        embedding_model=settings.EMBEDDING_MODEL,
                        timeout_seconds=settings.QDRANT_TIMEOUT_SECONDS,
                        retry_attempts=settings.EXTERNAL_RETRY_ATTEMPTS,
                        retry_base_seconds=(
                            settings.EXTERNAL_RETRY_BASE_SECONDS
                        ),
                        retry_max_seconds=(
                            settings.EXTERNAL_RETRY_MAX_SECONDS
                        ),
                        circuit_failure_threshold=(
                            settings.CIRCUIT_BREAKER_FAILURES
                        ),
                        circuit_reset_seconds=(
                            settings.CIRCUIT_BREAKER_RESET_SECONDS
                        ),
                        local_files_only=(
                            settings.EMBEDDING_LOCAL_FILES_ONLY
                        ),
                        catalog_path=settings.FOOD_CATALOG_PATH,
                    )
                    logger.info("Retrieval engine loaded.")

        return self.retriever

    def _get_agentic_workflow(self):
        if getattr(self, "agentic_workflow", None) is None:
            workflow_lock = getattr(
                self,
                "_agentic_workflow_lock",
                None,
            )
            if workflow_lock is None:
                workflow_lock = threading.Lock()
                self._agentic_workflow_lock = workflow_lock

            with workflow_lock:
                if getattr(self, "agentic_workflow", None) is None:
                    from rag.agentic_graph import AgenticRAGWorkflow
                    from rag.query_router import QueryRouter

                    self.agentic_workflow = AgenticRAGWorkflow(
                        retriever=self._get_retriever(),
                        min_score=settings.RAG_MIN_SCORE,
                        query_router=QueryRouter(
                            confidence_threshold=(
                                settings.QUERY_ROUTER_CONFIDENCE
                            )
                        ),
                    )
                    logger.info("Agentic RAG workflow loaded.")

        return self.agentic_workflow

    def warmup(self) -> None:
        self._get_agentic_workflow()

    def check_retrieval_ready(self) -> None:
        self._get_retriever().check_ready()

    def llm_health_status(self) -> str:
        if self.llm_circuit_breaker.state == "open":
            return "unavailable"
        return "configured"

    async def aclose(self) -> None:
        if self.retriever is not None:
            try:
                await asyncio.to_thread(self.retriever.close)
            except Exception:
                logger.exception("Không thể đóng Qdrant client.")

        try:
            await self.async_ai_client.close()
        except Exception:
            logger.exception("Không thể đóng AsyncOpenAI client.")

        try:
            await asyncio.to_thread(self.ai_client.close)
        except Exception:
            logger.exception("Không thể đóng OpenAI client.")

    @staticmethod
    def _clean_history(
        history: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        cleaned_history = []
        for message in history or []:
            role = message.get("role")
            content = message.get("content")
            if (
                role in {"user", "assistant"}
                and isinstance(content, str)
                and content.strip()
            ):
                cleaned_history.append(
                    {
                        "role": role,
                        "content": content.strip(),
                    }
                )
        return cleaned_history

    @staticmethod
    def _build_search_query(
        user_question: str,
        history: list[dict[str, str]],
    ) -> str:
        """Add the previous question when the current question is a short follow-up."""
        if len(normalize_text(user_question).split()) > 12:
            return user_question

        previous_question = next(
            (
                message["content"]
                for message in reversed(history)
                if message["role"] == "user"
            ),
            "",
        )
        if not previous_question:
            return user_question

        return f"{user_question}\n{previous_question[:300]}"

    def _prepare_messages(
        self,
        user_question: str,
        collection_name: str | None = None,
        district: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[
        str | None,
        list[dict[str, str]],
        list[dict],
    ]:
        greeting = _greeting_response(user_question)
        if greeting:
            return greeting, [], []

        cleaned_history = self._clean_history(history)
        search_query = self._build_search_query(
            user_question,
            cleaned_history,
        )
        agent_result = self._get_agentic_workflow().invoke(
            query=user_question,
            district=district,
            history=cleaned_history,
            collection_name=collection_name,
            search_query=search_query,
        )
        context_docs = agent_result.documents

        logger.info(
            "Agentic hybrid retrieval completed.",
            extra={
                "query_length": len(user_question),
                "result_count": len(context_docs),
                "district": agent_result.district or "-",
                "intent": agent_result.intent,
                "router_source": agent_result.intent_source,
                "router_confidence": agent_result.intent_confidence,
                "evidence_reason": agent_result.evidence_reason,
                "retry_count": agent_result.retry_count,
                "branch_counts": agent_result.branch_counts,
                "exact_shortcut_used": (
                    agent_result.exact_shortcut_used
                ),
            },
        )
        for idx, doc in enumerate(context_docs):
            logger.debug(
                "Qdrant result ranked.",
                extra={
                    "result_index": idx + 1,
                    "semantic_score": doc.get("score", 0),
                    "ranking_score": doc.get("ranking_score", 0),
                },
            )

        if not agent_result.should_generate:
            return agent_result.direct_answer or NO_RESULTS_MESSAGE, [], []

        if not context_docs:
            logger.warning("Agent returned generation mode without evidence.")
            return NO_RESULTS_MESSAGE, [], []

        structured_context = []
        for doc in context_docs:
            structured_context.append(
                {
                    "domain": doc.get("domain"),
                    "title": doc.get("title"),
                    "address": doc.get("address"),
                    "district": doc.get("district"),
                    "category": doc.get("category"),
                    "sub_category": doc.get("sub_category"),
                    "price_range": doc.get("price_range"),
                    "price_min": doc.get("price_min"),
                    "price_max": doc.get("price_max"),
                    "price_currency": doc.get("price_currency"),
                    "price_status": doc.get("price_status"),
                    "opening_hours": doc.get("opening_hours"),
                    "opening_intervals": doc.get(
                        "opening_intervals",
                        [],
                    ),
                    "opening_status": doc.get("opening_status"),
                    "opening_schedule_scope": doc.get(
                        "opening_schedule_scope",
                    ),
                    "tags": doc.get("tags", []),
                    # Keep the evidence prompt bounded even if a catalog
                    # entity has many chunks.
                    "description": str(doc.get("content", ""))[:1200],
                }
            )

        context_text = json.dumps(
            structured_context,
            ensure_ascii=False,
            indent=2,
        )

        user_content = f"""Dưới đây là dữ liệu chính xác được trích xuất từ hệ thống. Hãy dựa vào đó để xử lý yêu cầu của người dùng.

[NGỮ CẢNH CUNG CẤP]:
{context_text}

[CÂU HỎI NGƯỜI DÙNG]:
{user_question}"""

        messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
        messages.extend(cleaned_history)
        messages.append({"role": "user", "content": user_content})
        return None, messages, structured_context

    def run_with_metrics(
        self,
        user_question: str,
        collection_name: str | None = None,
        district: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict:
        started_at = time.perf_counter()
        direct_answer, messages, context = self._prepare_messages(
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
        )
        if direct_answer:
            return {
                "answer": direct_answer,
                "context": context,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms": round(
                    (time.perf_counter() - started_at) * 1000,
                    2,
                ),
            }

        logger.info("Bắt đầu gọi LLM cho câu hỏi đã truy xuất ngữ cảnh.")
        response = call_with_retry(
            lambda: self.ai_client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=800,
            ),
            attempts=settings.EXTERNAL_RETRY_ATTEMPTS,
            base_seconds=settings.EXTERNAL_RETRY_BASE_SECONDS,
            max_seconds=settings.EXTERNAL_RETRY_MAX_SECONDS,
            circuit_breaker=self.llm_circuit_breaker,
        )

        answer = response.choices[0].message.content
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("LLM trả về nội dung rỗng.")

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(
            getattr(usage, "completion_tokens", 0) or 0
        )
        logger.info("LLM đã trả lời thành công.")
        return {
            "answer": answer,
            "context": context,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": round(
                (time.perf_counter() - started_at) * 1000,
                2,
            ),
        }

    def run(
        self,
        user_question: str,
        collection_name: str | None = None,
        district: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        result = self.run_with_metrics(
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
        )
        return result["answer"]

    async def stream(
        self,
        user_question: str,
        collection_name: str | None = None,
        district: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        direct_answer, messages, _context = await asyncio.to_thread(
            self._prepare_messages,
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
        )
        if direct_answer:
            yield direct_answer
            return

        logger.info("Bắt đầu stream LLM cho câu hỏi đã truy xuất ngữ cảnh.")
        response_stream = await call_with_retry_async(
            lambda: self.async_ai_client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=800,
                stream=True,
            ),
            attempts=settings.EXTERNAL_RETRY_ATTEMPTS,
            base_seconds=settings.EXTERNAL_RETRY_BASE_SECONDS,
            max_seconds=settings.EXTERNAL_RETRY_MAX_SECONDS,
            circuit_breaker=self.llm_circuit_breaker,
        )

        received_content = False
        try:
            async for chunk in response_stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta.content
                if delta:
                    if not isinstance(delta, str):
                        raise RuntimeError(
                            "LLM stream trả về delta không hợp lệ."
                        )
                    received_content = True
                    yield delta
        except Exception:
            self.llm_circuit_breaker.record_failure()
            raise
        finally:
            await response_stream.close()

        if not received_content:
            raise RuntimeError("LLM stream trả về nội dung rỗng.")

        self.llm_circuit_breaker.record_success()
        logger.info("LLM đã stream câu trả lời thành công.")
