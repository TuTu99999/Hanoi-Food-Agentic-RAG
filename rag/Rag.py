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
from langsmith import traceable
from llm.provider import (
    OpenAICompatibleProvider,
    provider_config_from_settings,
)
from rag.map_links import append_directions_links
from rag.tracing import (
    reduce_stream,
    trace_inputs,
    trace_outputs,
    wrap_openai_if_enabled,
)


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
    "nguồn hiện có; 'weekly_source' là lịch tuần từ nguồn. Không tự khẳng định "
    "lịch ngày lễ hoặc ngày đặc biệt.\n"
    "7. Nếu verification_status là 'unverified', hãy coi giá và giờ mở cửa là "
    "dữ liệu tham khảo, không khẳng định rằng thông tin vừa được kiểm chứng.\n"
    "8. Chỉ chèn ảnh Markdown khi image_url có trong ngữ cảnh, dùng nguyên URL "
    "và tối đa một ảnh cho mỗi địa điểm. Không tự tạo URL; image_kind='place' "
    "là ảnh địa điểm, không phải ảnh món ăn. Nếu có metadata nguồn/giấy phép "
    "ảnh thì phải ghi kèm.\n"
    "9. Nếu distance_km có trong ngữ cảnh, hãy mô tả đó là khoảng cách ước tính "
    "theo tọa độ OpenStreetMap. Chỉ dùng đúng giá trị được cung cấp, không tự "
    "tính hoặc suy đoán khoảng cách."
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
        1. Kiểm tra API key của LLM provider trong .env.
        2. Khởi tạo client từ LLM_BASE_URL và LLM_MODEL.
        3. Khởi tạo lazy loading cho RetrievalEngine.
        """
        if not settings.LLM_API_KEY:
            raise RAGConfigurationError(
                "Không tìm thấy API key cho LLM provider đã chọn."
            )

        self.retriever = None
        self._retriever_lock = threading.Lock()
        self.agentic_workflow = None
        self._agentic_workflow_lock = threading.Lock()

        self.llm_provider = OpenAICompatibleProvider(
            provider_config_from_settings(settings),
            sync_client_factory=OpenAI,
            async_client_factory=AsyncOpenAI,
            client_wrapper=lambda client: wrap_openai_if_enabled(
                client,
                settings.LANGSMITH_TRACING,
            ),
        )
        self.ai_client = self.llm_provider.sync_client
        self.async_ai_client = self.llm_provider.async_client
        self.llm_model = self.llm_provider.model
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
        """Add context only when the current question refers to a previous turn."""
        normalized_question = f" {normalize_text(user_question)} "
        follow_up_phrases = (
            " vay ",
            " the ",
            " quan do ",
            " cho do ",
            " mon do ",
            " van gia ",
            " van nhu ",
            " nhu cu ",
            " con ",
            " no ",
        )
        if (
            len(normalized_question.split()) > 12
            or not any(
                phrase in normalized_question
                for phrase in follow_up_phrases
            )
        ):
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
        user_latitude: float | None = None,
        user_longitude: float | None = None,
        radius_km: float | None = None,
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
            user_latitude=user_latitude,
            user_longitude=user_longitude,
            radius_km=radius_km,
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
                "nearby_filter_applied": (
                    agent_result.nearby_filter_applied
                ),
                "radius_km": agent_result.radius_km,
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
                    "aliases": doc.get("aliases", []),
                    "cuisines": doc.get("cuisines", []),
                    "district_source": doc.get("district_source"),
                    "address_source": doc.get("address_source"),
                    "latitude": doc.get("latitude"),
                    "longitude": doc.get("longitude"),
                    "distance_km": doc.get("distance_km"),
                    "phone": doc.get("phone"),
                    "website": doc.get("website"),
                    "image_url": doc.get("image_url"),
                    "image_source_url": doc.get("image_source_url"),
                    "image_license": doc.get("image_license"),
                    "image_attribution": doc.get("image_attribution"),
                    "image_kind": doc.get("image_kind"),
                    "knowledge_version": doc.get("knowledge_version"),
                    "source_name": doc.get("source_name"),
                    "source_url": doc.get("source_url"),
                    "source_id": doc.get("source_id"),
                    "retrieved_at": doc.get("retrieved_at"),
                    "last_verified_at": doc.get("last_verified_at"),
                    "verification_status": doc.get(
                        "verification_status",
                        "unknown",
                    ),
                    "license": doc.get("license"),
                    "license_url": doc.get("license_url"),
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

    @traceable(
        name="food_rag_chat",
        run_type="chain",
        tags=["food", "agentic-rag"],
        project_name=settings.LANGSMITH_PROJECT,
        process_inputs=trace_inputs,
        process_outputs=trace_outputs,
        enabled=settings.LANGSMITH_TRACING,
    )
    def run_with_metrics(
        self,
        user_question: str,
        collection_name: str | None = None,
        district: str | None = None,
        history: list[dict[str, str]] | None = None,
        user_latitude: float | None = None,
        user_longitude: float | None = None,
        radius_km: float | None = None,
    ) -> dict:
        started_at = time.perf_counter()
        direct_answer, messages, context = self._prepare_messages(
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
            user_latitude=user_latitude,
            user_longitude=user_longitude,
            radius_km=radius_km,
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
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                reasoning_effort=settings.LLM_REASONING_EFFORT,
            ),
            attempts=settings.EXTERNAL_RETRY_ATTEMPTS,
            base_seconds=settings.EXTERNAL_RETRY_BASE_SECONDS,
            max_seconds=settings.EXTERNAL_RETRY_MAX_SECONDS,
            circuit_breaker=self.llm_circuit_breaker,
        )

        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            raise RuntimeError("LLM trả về câu trả lời bị cắt ngắn.")

        answer = choice.message.content
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("LLM trả về nội dung rỗng.")
        answer = append_directions_links(answer, context)

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
        user_latitude: float | None = None,
        user_longitude: float | None = None,
        radius_km: float | None = None,
    ) -> str:
        result = self.run_with_metrics(
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
            user_latitude=user_latitude,
            user_longitude=user_longitude,
            radius_km=radius_km,
        )
        return result["answer"]

    @traceable(
        name="food_rag_stream",
        run_type="chain",
        tags=["food", "agentic-rag", "stream"],
        project_name=settings.LANGSMITH_PROJECT,
        process_inputs=trace_inputs,
        reduce_fn=reduce_stream,
        enabled=settings.LANGSMITH_TRACING,
    )
    async def stream(
        self,
        user_question: str,
        collection_name: str | None = None,
        district: str | None = None,
        history: list[dict[str, str]] | None = None,
        user_latitude: float | None = None,
        user_longitude: float | None = None,
        radius_km: float | None = None,
    ) -> AsyncIterator[str]:
        direct_answer, messages, context = await asyncio.to_thread(
            self._prepare_messages,
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
            user_latitude=user_latitude,
            user_longitude=user_longitude,
            radius_km=radius_km,
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
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                reasoning_effort=settings.LLM_REASONING_EFFORT,
                stream=True,
            ),
            attempts=settings.EXTERNAL_RETRY_ATTEMPTS,
            base_seconds=settings.EXTERNAL_RETRY_BASE_SECONDS,
            max_seconds=settings.EXTERNAL_RETRY_MAX_SECONDS,
            circuit_breaker=self.llm_circuit_breaker,
        )

        received_content = False
        answer_parts = []
        finish_reason = None
        try:
            async for chunk in response_stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason

                delta = choice.delta.content
                if delta:
                    if not isinstance(delta, str):
                        raise RuntimeError(
                            "LLM stream trả về delta không hợp lệ."
                        )
                    received_content = True
                    answer_parts.append(delta)
                    yield delta
        except Exception:
            self.llm_circuit_breaker.record_failure()
            raise
        finally:
            try:
                await response_stream.close()
            except Exception as exc:
                logger.warning(
                    "Không thể đóng LLM stream sạch sẽ.",
                    extra={"error_type": type(exc).__name__},
                )

        if finish_reason == "length":
            raise RuntimeError("LLM stream trả về câu trả lời bị cắt ngắn.")
        if not received_content:
            raise RuntimeError("LLM stream trả về nội dung rỗng.")

        answer = "".join(answer_parts)
        answer_with_directions = append_directions_links(answer, context)
        cleaned_answer = answer.strip()
        directions_suffix = answer_with_directions[len(cleaned_answer):]
        if directions_suffix:
            yield directions_suffix

        self.llm_circuit_breaker.record_success()
        logger.info("LLM đã stream câu trả lời thành công.")
