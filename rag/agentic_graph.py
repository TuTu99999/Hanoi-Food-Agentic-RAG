import re
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from embedding.text_utils import normalize_text
from rag.query_router import QueryRouter


FOOD_DOMAIN = "food"
TOP_K = 5
EXACT_EVIDENCE_THRESHOLD = 0.84
KEYWORD_EVIDENCE_THRESHOLD = 0.35
DEFAULT_ROUTER_CONFIDENCE_THRESHOLD = 0.35

SUFFICIENT = "sufficient"
LOW_RELEVANCE = "low_relevance"
HARD_FILTER_EMPTY = "hard_filter_empty"
MISSING_REQUESTED_FIELD = "missing_requested_field"
AMBIGUOUS_ENTITY = "ambiguous_entity"
TOOL_ERROR = "tool_error"
OUT_OF_SCOPE = "out_of_scope"

HYBRID_SEARCH_MODES = ("exact", "keyword", "semantic")

HANOI_DISTRICTS = (
    "Hoàn Kiếm",
    "Ba Đình",
    "Tây Hồ",
    "Cầu Giấy",
    "Hai Bà Trưng",
    "Đống Đa",
    "Thanh Xuân",
    "Hoàng Mai",
    "Long Biên",
    "Nam Từ Liêm",
    "Bắc Từ Liêm",
    "Hà Đông",
    "Sơn Tây",
    "Thanh Trì",
    "Gia Lâm",
    "Đông Anh",
    "Sóc Sơn",
    "Thạch Thất",
    "Quốc Oai",
    "Chương Mỹ",
    "Đan Phượng",
    "Hoài Đức",
    "Mê Linh",
    "Mỹ Đức",
    "Phú Xuyên",
    "Phúc Thọ",
    "Thanh Oai",
    "Thường Tín",
    "Ứng Hòa",
    "Ba Vì",
)
NORMALIZED_DISTRICTS = {
    normalize_text(district): district
    for district in HANOI_DISTRICTS
}

ADDRESS_PHRASES = (
    "dia chi",
    "nam o dau",
    "o dau",
    "vi tri",
    "cho nao",
    "location",
)
PRICE_PHRASES = (
    "gia bao nhieu",
    "bao nhieu tien",
    "muc gia",
    "gia",
    "ngan sach",
)
OPENING_PHRASES = (
    "mo cua",
    "dong cua",
    "may gio",
    "luc nao",
    "con mo",
    "open",
)
REWRITE_FILLER_PHRASES = (
    "vui long",
    "co the",
    "cho toi",
    "cho minh",
    "cho t",
    "giup toi",
    "giup minh",
    "giup t",
    "toi muon",
    "minh muon",
    "xin hoi",
    "tim ho",
    "dia chi",
    "nam o dau",
    "o dau",
    "vi tri",
    "gia bao nhieu",
    "bao nhieu tien",
    "mo cua luc nao",
    "mo cua may gio",
)
REWRITE_FILLER_WORDS = {
    "a",
    "bao",
    "cho",
    "hoi",
    "nhe",
    "nha",
    "nhieu",
    "o",
    "t",
    "tim",
    "voi",
    "xin",
    "giup",
    "toi",
    "minh",
}
EMPTY_VALUES = {
    "",
    "unknown",
    "invalid",
    "missing",
    "none",
    "null",
    "n a",
    "khong ro",
    "chua co",
}
OUT_OF_SCOPE_PHRASES = (
    "bitcoin",
    "bong da",
    "chung khoan",
    "cai docker",
    "code",
    "email",
    "excel",
    "giai bai toan",
    "gia vang",
    "khach san",
    "laptop",
    "javascript",
    "ke chuyen",
    "marketing",
    "may tinh",
    "mo nhac",
    "phuong trinh",
    "python",
    "react",
    "soan cv",
    "tham quan",
    "thoi tiet",
    "tieng anh",
    "tong thong",
    "tom tat phim",
    "du lich",
    "ve may bay",
)
FOOD_SIGNAL_PHRASES = (
    "am thuc",
    "an sang",
    "banh",
    "bun",
    "ca phe",
    "cafe",
    "chao ga",
    "chao long",
    "chao suon",
    "che",
    "cho an",
    "com",
    "di an",
    "do uong",
    "do an",
    "hai san",
    "lau",
    "mon an",
    "nha hang",
    "noi an",
    "nuong",
    "oc",
    "pho",
    "pizza",
    "quan an",
    "sushi",
    "xoi",
)
ACCENTED_FOOD_SIGNAL_PHRASES = (
    "ăn",
    "cháo",
    "món",
    "quán",
)


class AgenticRAGState(TypedDict, total=False):
    original_query: str
    search_query: str
    history: list[dict[str, str]]
    collection_name: str | None
    district: str | None
    category_filter: str | None
    price_min_filter: int | None
    price_max_filter: int | None
    open_at_filter: str | None
    requested_fields: tuple[str, ...]
    has_food_signal: bool

    intent: str
    intent_confidence: float
    intent_source: str
    trusted_intent: bool

    search_modes: tuple[str, ...]
    allow_exact_shortcut: bool
    should_retrieve: bool

    documents: list[dict[str, Any]]
    candidate_count: int
    accepted_count: int
    filter_match_count: int | None
    branch_counts: dict[str, int]
    branch_errors: tuple[str, ...]
    exact_shortcut_used: bool
    retrieval_failed: bool

    evidence_reason: str
    retry_count: int
    answer_mode: str
    direct_answer: str | None
    next_step: str


@dataclass(frozen=True)
class AgenticRAGResult:
    answer_mode: str
    direct_answer: str | None
    documents: list[dict[str, Any]]
    intent: str
    intent_confidence: float
    intent_source: str
    district: str | None
    requested_fields: tuple[str, ...]
    search_modes: tuple[str, ...]
    search_query: str
    evidence_reason: str
    retry_count: int
    candidate_count: int
    accepted_count: int
    filter_match_count: int | None
    branch_counts: dict[str, int]
    branch_errors: tuple[str, ...]
    exact_shortcut_used: bool
    price_min_filter: int | None
    price_max_filter: int | None
    open_at_filter: str | None

    @property
    def should_generate(self) -> bool:
        return self.answer_mode == "grounded_generation"


class AgenticRAGWorkflow:
    """A small, controlled graph for food-only retrieval decisions."""

    def __init__(
        self,
        retriever,
        min_score: float,
        query_router: QueryRouter | None = None,
    ):
        if not 0 <= min_score <= 1:
            raise ValueError("min_score must be between 0 and 1")

        self.retriever = retriever
        self.min_score = min_score
        self.query_router = query_router or QueryRouter()
        self.graph = self._compile_graph()

    def _compile_graph(self):
        builder = StateGraph(AgenticRAGState)
        builder.add_node("analyze", self._analyze_node)
        builder.add_node("plan", self._plan_node)
        builder.add_node("retrieve", self._retrieve_node)
        builder.add_node("grade", self._grade_node)
        builder.add_node("rewrite", self._rewrite_node)

        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "plan")
        builder.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {
                "direct": END,
                "retrieve": "retrieve",
            },
        )
        builder.add_edge("retrieve", "grade")
        builder.add_conditional_edges(
            "grade",
            self._route_after_grade,
            {
                "end": END,
                "rewrite": "rewrite",
            },
        )
        builder.add_edge("rewrite", "retrieve")
        return builder.compile()

    def invoke(
        self,
        query: str,
        district: str | None = None,
        history: list[dict[str, str]] | None = None,
        collection_name: str | None = None,
        search_query: str | None = None,
    ) -> AgenticRAGResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must not be empty")

        graph_input = {
            "original_query": query.strip(),
            "search_query": (
                search_query.strip()
                if isinstance(search_query, str)
                and search_query.strip()
                else query.strip()
            ),
            "history": self._clean_history(history),
            "collection_name": collection_name,
            "district": district,
            "category_filter": None,
            "price_min_filter": None,
            "price_max_filter": None,
            "open_at_filter": None,
            "retry_count": 0,
            "documents": [],
            "candidate_count": 0,
            "accepted_count": 0,
            "filter_match_count": None,
            "branch_counts": {},
            "branch_errors": (),
            "exact_shortcut_used": False,
            "retrieval_failed": False,
            "answer_mode": "direct",
            "direct_answer": None,
        }
        final_state = self.graph.invoke(
            graph_input,
            config={
                "run_name": "agentic_hybrid_rag",
                "tags": ["food", "hybrid-retrieval"],
                "metadata": {
                    "collection": collection_name or "default",
                    "district": district or "all",
                },
            },
        )
        return AgenticRAGResult(
            answer_mode=final_state.get("answer_mode", "direct"),
            direct_answer=final_state.get("direct_answer"),
            documents=[
                dict(document)
                for document in final_state.get("documents", [])
            ],
            intent=final_state.get("intent", "unknown"),
            intent_confidence=float(
                final_state.get("intent_confidence", 0.0)
            ),
            intent_source=final_state.get("intent_source", "fallback"),
            district=final_state.get("district"),
            requested_fields=tuple(
                final_state.get("requested_fields", ())
            ),
            search_modes=tuple(final_state.get("search_modes", ())),
            search_query=final_state.get("search_query", query.strip()),
            evidence_reason=final_state.get(
                "evidence_reason",
                LOW_RELEVANCE,
            ),
            retry_count=int(final_state.get("retry_count", 0)),
            candidate_count=int(final_state.get("candidate_count", 0)),
            accepted_count=int(final_state.get("accepted_count", 0)),
            filter_match_count=final_state.get("filter_match_count"),
            branch_counts=dict(final_state.get("branch_counts", {})),
            branch_errors=tuple(final_state.get("branch_errors", ())),
            exact_shortcut_used=bool(
                final_state.get("exact_shortcut_used", False)
            ),
            price_min_filter=final_state.get("price_min_filter"),
            price_max_filter=final_state.get("price_max_filter"),
            open_at_filter=final_state.get("open_at_filter"),
        )

    def _analyze_node(self, state: AgenticRAGState) -> dict[str, Any]:
        query = state["original_query"]
        prediction = self._predict(query)
        intent = str(self._prediction_value(
            prediction,
            "intent",
            "unknown",
        ))
        confidence = self._safe_float(
            self._prediction_value(prediction, "confidence", 0.0)
        )
        source = str(self._prediction_value(
            prediction,
            "source",
            "fallback",
        ))
        trusted_intent = self._is_trusted_prediction(
            intent=intent,
            confidence=confidence,
            source=source,
        )
        price_min, price_max = self._extract_price_filters(
            query,
            state.get("history", []),
        )
        previous_query = self._previous_user_query(
            state.get("history", [])
        )
        district = self._resolve_district(
            query=query,
            provided_district=state.get("district"),
        )
        if (
            district is None
            and state.get("district") is None
            and previous_query
            and self._is_follow_up(query)
        ):
            district = self._resolve_district(
                query=previous_query,
                provided_district=None,
            )

        return {
            "district": district,
            "requested_fields": self._extract_requested_fields(query),
            "price_min_filter": price_min,
            "price_max_filter": price_max,
            "open_at_filter": self._extract_open_at(query),
            "has_food_signal": self._has_food_signal(query),
            "intent": intent,
            "intent_confidence": confidence,
            "intent_source": source,
            "trusted_intent": trusted_intent,
        }

    def _plan_node(self, state: AgenticRAGState) -> dict[str, Any]:
        intent = state.get("intent", "unknown")
        trusted_intent = bool(state.get("trusted_intent"))

        if trusted_intent and intent == "chitchat":
            return {
                "search_modes": (),
                "allow_exact_shortcut": False,
                "should_retrieve": False,
                "answer_mode": "direct",
                "direct_answer": (
                    "Xin chào! Mình có thể giúp bạn tìm quán ăn, món ăn, "
                    "địa chỉ, giá và giờ mở cửa tại Hà Nội."
                ),
                "evidence_reason": SUFFICIENT,
            }

        if (
            (trusted_intent and intent == OUT_OF_SCOPE)
            or self._is_clear_out_of_scope(state["original_query"])
        ):
            return {
                "search_modes": (),
                "allow_exact_shortcut": False,
                "should_retrieve": False,
                "answer_mode": "direct",
                "direct_answer": (
                    "Mình chỉ hỗ trợ thông tin và gợi ý ẩm thực tại Hà Nội."
                ),
                "evidence_reason": OUT_OF_SCOPE,
            }

        return {
            "search_modes": HYBRID_SEARCH_MODES,
            "allow_exact_shortcut": (
                (trusted_intent and intent == "entity_lookup")
                or bool(state.get("requested_fields"))
            ),
            "should_retrieve": True,
            "answer_mode": "grounded_generation",
            "direct_answer": None,
        }

    def _retrieve_node(self, state: AgenticRAGState) -> dict[str, Any]:
        try:
            retrieval_result = self.retriever.search_with_metadata(
                query=state["search_query"],
                top_k=TOP_K,
                district_filter=state.get("district"),
                domain_filter=FOOD_DOMAIN,
                category_filter=state.get("category_filter"),
                price_min_filter=state.get("price_min_filter"),
                price_max_filter=state.get("price_max_filter"),
                open_at_filter=state.get("open_at_filter"),
                min_score=self.min_score,
                collection_name=state.get("collection_name"),
                search_modes=state.get(
                    "search_modes",
                    HYBRID_SEARCH_MODES,
                ),
                allow_exact_shortcut=bool(
                    state.get("allow_exact_shortcut")
                ),
            )
        except (AttributeError, TypeError, ValueError):
            raise
        except Exception:
            return {
                "documents": [],
                "candidate_count": 0,
                "accepted_count": 0,
                "filter_match_count": None,
                "branch_counts": {},
                "branch_errors": ("retrieval",),
                "exact_shortcut_used": False,
                "retrieval_failed": True,
            }

        documents = [
            document
            for document in retrieval_result.documents
            if normalize_text(document.get("domain")) == FOOD_DOMAIN
        ]
        return {
            "documents": documents,
            "candidate_count": int(retrieval_result.candidate_count),
            "accepted_count": len(documents),
            "filter_match_count": retrieval_result.filter_match_count,
            "branch_counts": dict(retrieval_result.branch_counts),
            "branch_errors": tuple(retrieval_result.branch_errors),
            "exact_shortcut_used": bool(
                retrieval_result.exact_shortcut_used
            ),
            "retrieval_failed": False,
        }

    def _grade_node(self, state: AgenticRAGState) -> dict[str, Any]:
        documents = state.get("documents", [])
        hard_filter_exists = bool(
            state.get("district")
            or state.get("category_filter")
            or state.get("price_min_filter") is not None
            or state.get("price_max_filter") is not None
            or state.get("open_at_filter")
        )

        if state.get("retrieval_failed"):
            return self._safe_answer(
                TOOL_ERROR,
                "Hệ thống tìm kiếm đang tạm thời không khả dụng. "
                "Bạn vui lòng thử lại sau.",
            )

        if (
            not documents
            and hard_filter_exists
            and state.get("filter_match_count") == 0
        ):
            return self._safe_answer(
                HARD_FILTER_EMPTY,
                "Không tìm thấy quán ăn phù hợp với khu vực hoặc điều kiện "
                "đã chọn. Bạn có thể thử nới điều kiện tìm kiếm.",
            )

        if not documents:
            if state.get("branch_errors"):
                return self._safe_answer(
                    TOOL_ERROR,
                    "Hệ thống tìm kiếm đang tạm thời không khả dụng. "
                    "Bạn vui lòng thử lại sau.",
                )
            return self._low_relevance_result(state)

        allow_keyword_evidence = bool(state.get("has_food_signal"))
        evidence_documents = [
            document
            for document in documents
            if self._has_sufficient_score(
                document,
                allow_keyword_evidence=allow_keyword_evidence,
            )
        ]
        if not evidence_documents:
            if state.get("branch_errors"):
                return self._safe_answer(
                    TOOL_ERROR,
                    "Một phần hệ thống tìm kiếm đang tạm thời không khả dụng. "
                    "Bạn vui lòng thử lại sau.",
                )
            return self._low_relevance_result(state)

        ambiguity_message = self._build_ambiguity_message(
            evidence_documents
        )
        if ambiguity_message:
            return self._safe_answer(
                AMBIGUOUS_ENTITY,
                ambiguity_message,
            )

        requested_fields = state.get("requested_fields", ())
        complete_documents = [
            document
            for document in evidence_documents
            if all(
                self._document_has_field(document, field_name)
                for field_name in requested_fields
            )
        ]
        if requested_fields and not complete_documents:
            labels = {
                "address": "địa chỉ",
                "price": "giá",
                "opening": "giờ mở cửa",
            }
            missing_fields = [
                field_name
                for field_name in requested_fields
                if not any(
                    self._document_has_field(document, field_name)
                    for document in evidence_documents
                )
            ]
            field_text = ", ".join(
                labels[field_name]
                for field_name in missing_fields or requested_fields
            )
            return self._safe_answer(
                MISSING_REQUESTED_FIELD,
                f"Dữ liệu hiện tại chưa có thông tin {field_text} "
                "đủ rõ để xác nhận.",
            )

        return {
            "evidence_reason": SUFFICIENT,
            "answer_mode": "grounded_generation",
            "direct_answer": None,
            "documents": complete_documents or evidence_documents,
            "accepted_count": len(
                complete_documents or evidence_documents
            ),
            "next_step": "end",
        }

    def _rewrite_node(self, state: AgenticRAGState) -> dict[str, Any]:
        rewritten_query = self._rewrite_query(state["search_query"])
        return {
            "search_query": rewritten_query,
            "retry_count": min(
                int(state.get("retry_count", 0)) + 1,
                1,
            ),
            # Hard filters are deliberately not changed here.
            "district": state.get("district"),
            "category_filter": state.get("category_filter"),
            "price_min_filter": state.get("price_min_filter"),
            "price_max_filter": state.get("price_max_filter"),
            "open_at_filter": state.get("open_at_filter"),
        }

    @staticmethod
    def _route_after_plan(state: AgenticRAGState) -> str:
        return "retrieve" if state.get("should_retrieve") else "direct"

    @staticmethod
    def _route_after_grade(state: AgenticRAGState) -> str:
        return state.get("next_step", "end")

    @staticmethod
    def _clean_history(
        history: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        cleaned = []
        for message in history or []:
            role = message.get("role")
            content = message.get("content")
            if (
                role in {"user", "assistant"}
                and isinstance(content, str)
                and content.strip()
            ):
                cleaned.append(
                    {
                        "role": role,
                        "content": content.strip(),
                    }
                )
        return cleaned

    def _predict(self, query: str):
        try:
            return self.query_router.predict(query)
        except Exception:
            return {
                "intent": "unknown",
                "confidence": 0.0,
                "source": "fallback",
            }

    @staticmethod
    def _prediction_value(
        prediction,
        name: str,
        default: Any,
    ) -> Any:
        if isinstance(prediction, dict):
            return prediction.get(name, default)
        return getattr(prediction, name, default)

    def _is_trusted_prediction(
        self,
        *,
        intent: str,
        confidence: float,
        source: str,
    ) -> bool:
        if intent == "unknown" or source in {"fallback", "low_confidence"}:
            return False
        threshold = self._safe_float(
            getattr(
                self.query_router,
                "confidence_threshold",
                DEFAULT_ROUTER_CONFIDENCE_THRESHOLD,
            )
        )
        return confidence >= threshold

    @staticmethod
    def _resolve_district(
        *,
        query: str,
        provided_district: str | None,
    ) -> str | None:
        normalized_query = f" {normalize_text(query)} "
        matches = []
        for normalized_district, canonical_district in (
            NORMALIZED_DISTRICTS.items()
        ):
            position = normalized_query.find(
                f" {normalized_district} "
            )
            if position >= 0:
                matches.append((position, canonical_district))

        if matches:
            return min(matches, key=lambda item: item[0])[1]

        normalized_provided = normalize_text(provided_district)
        if normalized_provided in {"", "tat ca", "all", "none"}:
            return None
        return NORMALIZED_DISTRICTS.get(
            normalized_provided,
        )

    @staticmethod
    def _is_clear_out_of_scope(query: str) -> bool:
        normalized_query = f" {normalize_text(query)} "
        return any(
            f" {phrase} " in normalized_query
            for phrase in OUT_OF_SCOPE_PHRASES
        )

    @staticmethod
    def _extract_requested_fields(query: str) -> tuple[str, ...]:
        normalized_query = normalize_text(query)
        padded_query = f" {normalized_query} "
        requested_fields = []

        if any(
            f" {phrase} " in padded_query
            for phrase in ADDRESS_PHRASES
        ):
            requested_fields.append("address")

        if (
            any(
                f" {phrase} " in padded_query
                for phrase in PRICE_PHRASES
            )
            or re.search(
                r"\b\d+(?:\s+\d{3})*\s*(?:k|d|dong|nghin|ngan)\b",
                normalized_query,
            )
        ):
            requested_fields.append("price")

        if (
            any(
                f" {phrase} " in padded_query
                for phrase in OPENING_PHRASES
            )
            or re.search(
                r"\b(?:sau|truoc)\s+\d{1,2}(?::\d{2}|h)?\b",
                normalized_query,
            )
        ):
            requested_fields.append("opening")

        return tuple(requested_fields)

    @staticmethod
    def _extract_price_max(query: str) -> int | None:
        normalized_query = normalize_text(query)
        amount_pattern = (
            r"(\d+(?:\s+\d{3})*)\s*"
            r"(k|nghin|ngan|dong|d)?"
        )
        range_match = re.search(
            rf"(?:tu\s+)?{amount_pattern}\s+den\s+{amount_pattern}",
            normalized_query,
        )
        if range_match:
            return AgenticRAGWorkflow._price_amount(
                range_match.group(3),
                range_match.group(4),
            )

        match = re.search(
            rf"(?:duoi|toi da|khong qua|ngan sach(?: la)?|tam)"
            rf"\s+{amount_pattern}",
            normalized_query,
        )
        if not match:
            match = re.search(
                rf"{amount_pattern}\s+(?:do ve|tro xuong)",
                normalized_query,
            )
        if not match:
            return None

        return AgenticRAGWorkflow._price_amount(
            match.group(1),
            match.group(2),
        )

    @staticmethod
    def _extract_price_min(query: str) -> int | None:
        normalized_query = normalize_text(query)
        amount_pattern = (
            r"(\d+(?:\s+\d{3})*)\s*"
            r"(k|nghin|ngan|dong|d)?"
        )
        range_match = re.search(
            rf"(?:tu\s+)?{amount_pattern}\s+den\s+{amount_pattern}",
            normalized_query,
        )
        if range_match:
            return AgenticRAGWorkflow._price_amount(
                range_match.group(1),
                range_match.group(2),
            )

        match = re.search(
            rf"(?:tren|toi thieu|it nhat|tu)\s+{amount_pattern}",
            normalized_query,
        )
        if not match:
            match = re.search(
                rf"{amount_pattern}\s+(?:do len|tro len)",
                normalized_query,
            )
        if not match:
            return None

        return AgenticRAGWorkflow._price_amount(
            match.group(1),
            match.group(2),
        )

    @staticmethod
    def _price_amount(raw_number: str, unit: str | None) -> int | None:
        amount = int(raw_number.replace(" ", ""))
        if unit in {"k", "nghin", "ngan"}:
            amount *= 1000
        elif " " not in raw_number and amount <= 1000:
            amount *= 1000
        return amount if amount > 0 else None

    @classmethod
    def _extract_price_filters(
        cls,
        query: str,
        history: list[dict[str, str]],
    ) -> tuple[int | None, int | None]:
        price_min = cls._extract_price_min(query)
        price_max = cls._extract_price_max(query)
        if price_min is not None or price_max is not None:
            return price_min, price_max

        previous_query = cls._previous_user_query(history)
        if not previous_query or not cls._is_follow_up(query):
            return None, None
        return (
            cls._extract_price_min(previous_query),
            cls._extract_price_max(previous_query),
        )

    @staticmethod
    def _previous_user_query(
        history: list[dict[str, str]],
    ) -> str | None:
        for message in reversed(history):
            if message.get("role") == "user":
                content = message.get("content", "").strip()
                if content:
                    return content
        return None

    @staticmethod
    def _is_follow_up(query: str) -> bool:
        normalized_query = f" {normalize_text(query)} "
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
        return any(
            phrase in normalized_query
            for phrase in follow_up_phrases
        )

    @staticmethod
    def _extract_open_at(query: str) -> str | None:
        normalized_query = normalize_text(query)
        has_opening_word = any(
            phrase in normalized_query
            for phrase in ("mo cua", "dong cua", "con mo")
        )
        has_time_marker = bool(
            re.search(r"\d{1,2}\s*(?::\d{1,2}|h)", query.casefold())
        )
        if not has_opening_word and not has_time_marker:
            return None

        match = re.search(
            r"(?:sau|lúc|luc)\s*(\d{1,2})"
            r"(?:(?::|h)\s*(\d{1,2})?)?",
            query.casefold(),
        )
        if not match:
            return None

        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _has_food_signal(query: str) -> bool:
        normalized_query = f" {normalize_text(query)} "
        normalized_match = any(
            f" {phrase} " in normalized_query
            for phrase in FOOD_SIGNAL_PHRASES
        )
        accented_match = any(
            re.search(
                rf"(?<!\w){re.escape(phrase)}(?!\w)",
                query.casefold(),
            )
            for phrase in ACCENTED_FOOD_SIGNAL_PHRASES
        )
        return normalized_match or accented_match

    def _has_sufficient_score(
        self,
        document: dict[str, Any],
        *,
        allow_keyword_evidence: bool,
    ) -> bool:
        exact_score = self._safe_float(document.get("exact_score", 0.0))
        semantic_score = self._safe_float(
            document.get(
                "semantic_score",
                document.get("score", 0.0),
            )
        )
        keyword_coverage = self._safe_float(
            document.get("keyword_coverage", 0.0)
        )
        return (
            exact_score >= EXACT_EVIDENCE_THRESHOLD
            or semantic_score >= self.min_score
            or (
                allow_keyword_evidence
                and keyword_coverage >= KEYWORD_EVIDENCE_THRESHOLD
            )
        )

    @staticmethod
    def _build_ambiguity_message(
        documents: list[dict[str, Any]],
    ) -> str | None:
        if not documents:
            return None

        top_title = normalize_text(
            documents[0].get("title_normalized")
            or documents[0].get("title")
        )
        if not top_title:
            return None

        matching_documents = []
        seen_parents = set()
        for index, document in enumerate(documents):
            document_title = normalize_text(
                document.get("title_normalized")
                or document.get("title")
            )
            if document_title != top_title:
                continue
            if AgenticRAGWorkflow._safe_float(
                document.get("exact_score", 0.0)
            ) < EXACT_EVIDENCE_THRESHOLD:
                continue

            parent_key = (
                document.get("parent_id")
                or document.get("address")
                or f"result:{index}"
            )
            if parent_key in seen_parents:
                continue
            seen_parents.add(parent_key)
            matching_documents.append(document)

        if len(matching_documents) < 2:
            return None

        addresses = []
        for document in matching_documents:
            address = str(document.get("address") or "").strip()
            if address and address not in addresses:
                addresses.append(address)
            if len(addresses) == 3:
                break

        title = str(documents[0].get("title") or "này").strip()
        if len(addresses) == 1:
            return (
                f"Dữ liệu về {title} đang có nhiều bản ghi cùng địa chỉ "
                "nhưng chưa đồng nhất. Mình chưa thể chọn một bản ghi tùy ý."
            )
        if addresses:
            return (
                f"Có nhiều quán cùng tên {title}. Bạn muốn chọn địa chỉ nào: "
                f"{'; '.join(addresses)}?"
            )
        return (
            f"Có nhiều quán cùng tên {title}. "
            "Bạn có thể cho mình thêm khu vực hoặc địa chỉ không?"
        )

    @staticmethod
    def _document_has_field(
        document: dict[str, Any],
        field_name: str,
    ) -> bool:
        if field_name == "address":
            return AgenticRAGWorkflow._has_text_value(
                document.get("address")
            )

        if field_name == "price":
            status = normalize_text(document.get("price_status"))
            if status in {"unknown", "invalid", "missing"}:
                return False
            if (
                document.get("price_min") is not None
                or document.get("price_max") is not None
            ):
                return True
            return AgenticRAGWorkflow._has_text_value(
                document.get("price_range")
            )

        if field_name == "opening":
            status = normalize_text(document.get("opening_status"))
            if status in {"unknown", "invalid", "missing"}:
                return False
            if document.get("opening_intervals"):
                return True
            return AgenticRAGWorkflow._has_text_value(
                document.get("opening_hours")
            )

        return False

    @staticmethod
    def _has_text_value(value: Any) -> bool:
        return normalize_text(str(value or "")) not in EMPTY_VALUES

    @staticmethod
    def _low_relevance_result(
        state: AgenticRAGState,
    ) -> dict[str, Any]:
        if int(state.get("retry_count", 0)) < 1:
            return {
                "evidence_reason": LOW_RELEVANCE,
                "next_step": "rewrite",
            }
        return AgenticRAGWorkflow._safe_answer(
            LOW_RELEVANCE,
            "Dựa trên dữ liệu hiện tại, hệ thống chưa tìm thấy thông tin "
            "ẩm thực đủ liên quan đến câu hỏi của bạn.",
        )

    @staticmethod
    def _safe_answer(reason: str, message: str) -> dict[str, Any]:
        return {
            "evidence_reason": reason,
            "answer_mode": "direct",
            "direct_answer": message,
            "next_step": "end",
        }

    @staticmethod
    def _rewrite_query(query: str) -> str:
        rewritten = f" {normalize_text(query)} "
        for phrase in sorted(
            REWRITE_FILLER_PHRASES,
            key=len,
            reverse=True,
        ):
            rewritten = rewritten.replace(f" {phrase} ", " ")

        tokens = [
            token
            for token in rewritten.split()
            if token not in REWRITE_FILLER_WORDS
        ]
        result = " ".join(tokens).strip()
        return result or query.strip()

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
