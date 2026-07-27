import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sentence_transformers import SentenceTransformer

from core.resilience import CircuitBreaker, call_with_retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
DEFAULT_COLLECTION_ALIAS = os.getenv(
    "QDRANT_COLLECTION",
    "hanoi_knowledge_current",
)
DEFAULT_MIN_SCORE = 0.5
STRONG_TITLE_MATCH = 0.82
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
DEFAULT_QDRANT_TIMEOUT = float(
    os.getenv("QDRANT_TIMEOUT_SECONDS", "5")
)
DEFAULT_RETRY_ATTEMPTS = int(
    os.getenv("EXTERNAL_RETRY_ATTEMPTS", "3")
)
DEFAULT_RETRY_BASE_SECONDS = float(
    os.getenv("EXTERNAL_RETRY_BASE_SECONDS", "0.25")
)
DEFAULT_RETRY_MAX_SECONDS = float(
    os.getenv("EXTERNAL_RETRY_MAX_SECONDS", "2")
)
DEFAULT_CIRCUIT_FAILURES = int(
    os.getenv("CIRCUIT_BREAKER_FAILURES", "5")
)
DEFAULT_CIRCUIT_RESET_SECONDS = float(
    os.getenv("CIRCUIT_BREAKER_RESET_SECONDS", "30")
)
DEFAULT_LOCAL_FILES_ONLY = os.getenv(
    "EMBEDDING_LOCAL_FILES_ONLY",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}


def normalize_text(value: Optional[str]) -> str:
    """Normalize Vietnamese text for exact filters and simple matching."""
    if not value:
        return ""

    normalized = unicodedata.normalize("NFD", value.lower())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    normalized = normalized.replace("đ", "d")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


class RetrievalEngine:
    def __init__(
        self,
        qdrant_host: Optional[str] = None,
        qdrant_port: Optional[int] = None,
        collection_name: str = DEFAULT_COLLECTION_ALIAS,
        qdrant_url: Optional[str] = None,
        qdrant_api_key: Optional[str] = None,
        embedding_model: str = EMBEDDING_MODEL,
        timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_base_seconds: float = DEFAULT_RETRY_BASE_SECONDS,
        retry_max_seconds: float = DEFAULT_RETRY_MAX_SECONDS,
        circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURES,
        circuit_reset_seconds: float = DEFAULT_CIRCUIT_RESET_SECONDS,
        local_files_only: bool = DEFAULT_LOCAL_FILES_ONLY,
    ):
        configured_url = (
            qdrant_url
            or os.getenv("QDRANT_URL", "").strip().rstrip("/")
        )
        configured_api_key = (
            qdrant_api_key
            if qdrant_api_key is not None
            else os.getenv("QDRANT_API_KEY", "").strip() or None
        )

        if configured_url:
            self.client = QdrantClient(
                url=configured_url,
                api_key=configured_api_key,
                timeout=timeout_seconds,
            )
        else:
            host = qdrant_host or os.getenv("QDRANT_HOST", "localhost").strip()
            port = (
                qdrant_port
                if qdrant_port is not None
                else int(os.getenv("QDRANT_PORT", "6333"))
            )
            self.client = QdrantClient(
                host=host,
                port=port,
                api_key=configured_api_key,
                timeout=timeout_seconds,
            )
        self.model = SentenceTransformer(
            embedding_model,
            local_files_only=local_files_only,
        )
        self.collection_name = collection_name
        self.retry_attempts = retry_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            reset_seconds=circuit_reset_seconds,
        )

    def search(
        self,
        query: str,
        top_k: int = 3,
        district_filter: Optional[str] = None,
        domain_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        min_score: float = DEFAULT_MIN_SCORE,
        collection_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search semantic candidates, filter weak results, then rerank by
        title and address. The default collection name is a Qdrant alias.
        """
        query = query.strip()
        if not query:
            return []
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")
        if not -1 <= min_score <= 1:
            raise ValueError("min_score must be between -1 and 1.")

        query_vector = self.model.encode(query).tolist()
        search_filter = self._build_filter(
            district=district_filter,
            domain=domain_filter,
            category=category_filter,
        )

        # More candidates give the lightweight lexical reranker room to fix
        # small spelling mistakes without adding another search service.
        candidate_limit = min(max(top_k * 20, 100), 200)
        raw_results = call_with_retry(
            lambda: self.client.search(
                collection_name=collection_name or self.collection_name,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=candidate_limit,
                with_payload=True,
            ),
            attempts=self.retry_attempts,
            base_seconds=self.retry_base_seconds,
            max_seconds=self.retry_max_seconds,
            circuit_breaker=self.circuit_breaker,
        )

        documents = []
        for hit in raw_results:
            semantic_score = float(hit.score)
            document = self._to_document(hit.payload or {}, semantic_score)
            title_match_score = self._field_match_score(
                query,
                document["title"],
            )
            address_match_score = self._field_match_score(
                query,
                document["address"],
            )

            # An explicit or close title match is useful even when the
            # embedding score is slightly below the semantic threshold.
            if (
                semantic_score < min_score
                and title_match_score < STRONG_TITLE_MATCH
            ):
                continue

            document["match_score"] = self._calculate_match_score(
                title_match_score=title_match_score,
                address_match_score=address_match_score,
            )
            document["ranking_score"] = round(
                document["score"] + document["match_score"],
                6,
            )
            documents.append(document)

        documents.sort(
            key=lambda document: (
                document["ranking_score"],
                document["score"],
            ),
            reverse=True,
        )
        return self._group_by_parent(documents)[:top_k]

    def check_ready(self) -> None:
        self.client.get_collection(self.collection_name)

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _build_filter(
        district: Optional[str],
        domain: Optional[str],
        category: Optional[str],
    ) -> Optional[Filter]:
        conditions = []

        normalized_district = normalize_text(district)
        if normalized_district:
            conditions.append(
                FieldCondition(
                    key="district_normalized",
                    match=MatchValue(value=normalized_district),
                )
            )

        normalized_domain = normalize_text(domain)
        if normalized_domain:
            conditions.append(
                FieldCondition(
                    key="domain",
                    match=MatchValue(value=normalized_domain),
                )
            )

        normalized_category = normalize_text(category)
        if normalized_category:
            conditions.append(
                FieldCondition(
                    key="category_normalized",
                    match=MatchValue(value=normalized_category),
                )
            )

        return Filter(must=conditions) if conditions else None

    @classmethod
    def _to_document(
        cls,
        payload: Dict[str, Any],
        score: float,
    ) -> Dict[str, Any]:
        """Return one stable document shape for both new and legacy payloads."""
        metadata = payload.get("metadata") or {}

        def value(key: str, default: Any = "") -> Any:
            payload_value = payload.get(key)
            if payload_value is not None:
                return payload_value
            return metadata.get(key, default)

        content = (
            value("description")
            or value("content")
            or payload.get("vector_text", "")
        )
        district = value("district")

        return {
            "score": score,
            "chunk_id": value("chunk_id"),
            "chunk_index": value("chunk_index", 0),
            "parent_id": value("parent_id"),
            "domain": value("domain"),
            "title": value("title"),
            "address": value("address"),
            "district": district,
            "district_normalized": (
                value("district_normalized") or normalize_text(district)
            ),
            "category": value("category"),
            "sub_category": value("sub_category"),
            "price_range": value("price_range"),
            "opening_hours": value("opening_hours"),
            "tags": value("tags", []),
            "content": content,
            # Keep "text" during the RAG integration transition.
            "text": content,
        }

    @staticmethod
    def _calculate_match_score(
        title_match_score: float,
        address_match_score: float,
    ) -> float:
        # A title match matters more than an address match. The total lexical
        # bonus stays below the semantic score's full range.
        title_bonus = title_match_score if title_match_score >= 0.6 else 0.0
        address_bonus = (
            address_match_score if address_match_score >= 0.6 else 0.0
        )
        return round(
            (title_bonus * 0.35)
            + (address_bonus * 0.15),
            6,
        )

    @staticmethod
    def _group_by_parent(
        documents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge relevant chunks so each returned item represents one entity."""
        grouped_documents: Dict[str, Dict[str, Any]] = {}

        for index, document in enumerate(documents):
            parent_id = document.get("parent_id")
            chunk_id = document.get("chunk_id")
            if parent_id not in (None, ""):
                group_key = f"parent:{parent_id}"
            elif chunk_id not in (None, ""):
                group_key = f"chunk:{chunk_id}"
            else:
                group_key = f"result:{index}"

            existing_document = grouped_documents.get(group_key)
            if existing_document is None:
                grouped_document = document.copy()
                grouped_document["_chunks"] = (
                    [(document.get("chunk_index", 0), chunk_id)]
                    if chunk_id not in (None, "")
                    else []
                )
                grouped_document["_contents"] = (
                    [(document.get("chunk_index", 0), document["content"])]
                    if document["content"]
                    else []
                )
                grouped_documents[group_key] = grouped_document
                continue

            if (
                chunk_id not in (None, "")
                and chunk_id
                not in {
                    stored_chunk_id
                    for _, stored_chunk_id in existing_document["_chunks"]
                }
            ):
                existing_document["_chunks"].append(
                    (document.get("chunk_index", 0), chunk_id)
                )

            content = document["content"]
            if (
                content
                and content
                not in {
                    stored_content
                    for _, stored_content in existing_document["_contents"]
                }
            ):
                existing_document["_contents"].append(
                    (document.get("chunk_index", 0), content)
                )

        results = []
        for document in grouped_documents.values():
            chunks = sorted(document.pop("_chunks"))
            contents = sorted(document.pop("_contents"))
            document["chunk_ids"] = [chunk_id for _, chunk_id in chunks]
            combined_content = "\n\n".join(
                content for _, content in contents
            )
            document["content"] = combined_content
            document["text"] = combined_content
            results.append(document)

        return results

    @staticmethod
    def _field_match_score(query: str, field_value: str) -> float:
        normalized_query = normalize_text(query)
        normalized_field = normalize_text(field_value)
        if not normalized_query or not normalized_field:
            return 0.0

        if normalized_field in normalized_query:
            return 1.0

        query_tokens = normalized_query.split()
        field_tokens = normalized_field.split()
        if not field_tokens:
            return 0.0

        matched_tokens = 0
        for field_token in field_tokens:
            best_ratio = max(
                SequenceMatcher(None, field_token, query_token).ratio()
                for query_token in query_tokens
            )
            minimum_ratio = 1.0 if len(field_token) <= 2 else 0.82
            if best_ratio >= minimum_ratio:
                matched_tokens += 1

        token_coverage = matched_tokens / len(field_tokens)
        sequence_ratio = SequenceMatcher(
            None,
            normalized_field,
            normalized_query,
        ).ratio()
        return max(token_coverage, sequence_ratio)
