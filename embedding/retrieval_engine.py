import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
from sentence_transformers import SentenceTransformer

from core.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    call_with_retry,
    is_retryable_error,
)
from embedding.catalog_schema import (
    is_open_at,
    parse_opening_hours,
    parse_price_range,
)
from embedding.lexical_index import LexicalIndex
from embedding.text_utils import field_match_score, normalize_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
logger = logging.getLogger(__name__)
DEFAULT_COLLECTION_ALIAS = os.getenv(
    "QDRANT_COLLECTION",
    "hanoi_food_current",
)
DEFAULT_CATALOG_PATH = Path(
    os.getenv(
        "FOOD_CATALOG_PATH",
        str(PROJECT_ROOT / "data" / "processed" / "food_chunks.json"),
    )
)
DEFAULT_MIN_SCORE = 0.5
STRONG_TITLE_MATCH = 0.82
EXACT_SHORTCUT_SCORE = 0.98
RRF_K = 60
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
DEFAULT_QDRANT_TIMEOUT = float(
    os.getenv("QDRANT_TIMEOUT_SECONDS", "1")
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


@dataclass
class RetrievalResult:
    documents: List[Dict[str, Any]]
    candidate_count: int
    accepted_count: int
    filter_match_count: Optional[int]
    branch_counts: Dict[str, int] = field(default_factory=dict)
    branch_errors: List[str] = field(default_factory=list)
    exact_shortcut_used: bool = False


class RetrievalConfigurationError(RuntimeError):
    pass


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
        catalog_path: Path | str = DEFAULT_CATALOG_PATH,
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
            host = qdrant_host or os.getenv(
                "QDRANT_HOST",
                "127.0.0.1",
            ).strip()
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
        resolved_catalog_path = Path(catalog_path)
        if not resolved_catalog_path.is_absolute():
            resolved_catalog_path = PROJECT_ROOT / resolved_catalog_path
        self.lexical_index = self._load_lexical_index(
            resolved_catalog_path,
        )
        if self.lexical_index is None:
            raise RetrievalConfigurationError(
                "Food catalog is required for hybrid retrieval."
            )

    @classmethod
    def for_lexical_search(
        cls,
        catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    ) -> "RetrievalEngine":
        """Build exact/BM25 search without loading Qdrant or a model."""
        engine = cls.__new__(cls)
        resolved_path = Path(catalog_path)
        if not resolved_path.is_absolute():
            resolved_path = PROJECT_ROOT / resolved_path
        engine.lexical_index = cls._load_lexical_index(resolved_path)
        if engine.lexical_index is None:
            raise RetrievalConfigurationError(
                "Food catalog is required for lexical retrieval."
            )
        return engine

    def search(
        self,
        query: str,
        top_k: int = 3,
        district_filter: Optional[str] = None,
        domain_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        price_min_filter: Optional[int] = None,
        price_max_filter: Optional[int] = None,
        open_at_filter: Optional[str] = None,
        min_score: float = DEFAULT_MIN_SCORE,
        collection_name: Optional[str] = None,
        search_modes: Optional[tuple[str, ...]] = None,
        allow_exact_shortcut: bool = False,
    ) -> List[Dict[str, Any]]:
        return self.search_with_metadata(
            query=query,
            top_k=top_k,
            district_filter=district_filter,
            domain_filter=domain_filter,
            category_filter=category_filter,
            price_min_filter=price_min_filter,
            price_max_filter=price_max_filter,
            open_at_filter=open_at_filter,
            min_score=min_score,
            collection_name=collection_name,
            search_modes=search_modes,
            allow_exact_shortcut=allow_exact_shortcut,
        ).documents

    def search_with_metadata(
        self,
        query: str,
        top_k: int = 3,
        district_filter: Optional[str] = None,
        domain_filter: Optional[str] = "food",
        category_filter: Optional[str] = None,
        price_min_filter: Optional[int] = None,
        price_max_filter: Optional[int] = None,
        open_at_filter: Optional[str] = None,
        min_score: float = DEFAULT_MIN_SCORE,
        collection_name: Optional[str] = None,
        search_modes: Optional[tuple[str, ...]] = None,
        allow_exact_shortcut: bool = False,
    ) -> RetrievalResult:
        """
        Run independent exact, BM25 and semantic branches, then fuse ranks.

        Food is enforced at this tool boundary so a planner cannot
        accidentally mix travel documents into the answer.
        """
        query = query.strip()
        if not query:
            return RetrievalResult([], 0, 0, 0)
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")
        if not -1 <= min_score <= 1:
            raise ValueError("min_score must be between -1 and 1.")
        if price_min_filter is not None and price_min_filter <= 0:
            raise ValueError("price_min_filter must be greater than zero.")
        if price_max_filter is not None and price_max_filter <= 0:
            raise ValueError("price_max_filter must be greater than zero.")
        if (
            price_min_filter is not None
            and price_max_filter is not None
            and price_min_filter > price_max_filter
        ):
            raise ValueError(
                "price_min_filter cannot be greater than price_max_filter."
            )
        if domain_filter and normalize_text(domain_filter) != "food":
            raise ValueError("This retrieval engine only supports food data.")

        modes = search_modes or ("exact", "keyword", "semantic")
        allowed_modes = {"exact", "keyword", "semantic"}
        if not modes or any(mode not in allowed_modes for mode in modes):
            raise ValueError("search_modes contains an unsupported mode.")

        lexical_index = getattr(self, "lexical_index", None)
        filter_match_count = (
            lexical_index.count_matching_filters(
                district=district_filter,
                category=category_filter,
                price_min=price_min_filter,
                price_max=price_max_filter,
                open_at=open_at_filter,
            )
            if lexical_index is not None
            else None
        )
        result_groups: dict[str, list[dict[str, Any]]] = {}
        branch_errors: list[str] = []
        semantic_candidate_count = 0

        if "exact" in modes and lexical_index is not None:
            result_groups["exact"] = lexical_index.exact_search(
                query=query,
                district=district_filter,
                category=category_filter,
                price_min=price_min_filter,
                price_max=price_max_filter,
                open_at=open_at_filter,
                limit=max(top_k * 3, 10),
            )

            exact_results = result_groups["exact"]
            strong_exact_results = [
                document
                for document in exact_results
                if document["exact_score"] >= EXACT_SHORTCUT_SCORE
            ]
            if (
                allow_exact_shortcut
                and len(strong_exact_results) == 1
            ):
                documents = self._fuse_rankings(
                    {"exact": strong_exact_results},
                    top_k=top_k,
                )
                return RetrievalResult(
                    documents=documents,
                    candidate_count=len(exact_results),
                    accepted_count=len(documents),
                    filter_match_count=filter_match_count,
                    branch_counts={"exact": len(exact_results)},
                    exact_shortcut_used=True,
                )

        if "keyword" in modes and lexical_index is not None:
            result_groups["keyword"] = lexical_index.keyword_search(
                query=query,
                district=district_filter,
                category=category_filter,
                price_min=price_min_filter,
                price_max=price_max_filter,
                open_at=open_at_filter,
                limit=max(top_k * 5, 20),
            )

        if "semantic" in modes:
            try:
                semantic_results, semantic_candidate_count = (
                    self._semantic_search(
                        query=query,
                        top_k=max(top_k * 4, 20),
                        district_filter=district_filter,
                        category_filter=category_filter,
                        price_min_filter=price_min_filter,
                        price_max_filter=price_max_filter,
                        open_at_filter=open_at_filter,
                        min_score=min_score,
                        collection_name=collection_name,
                    )
                )
                self._validate_knowledge_versions(semantic_results)
                result_groups["semantic"] = semantic_results
            except Exception as exc:
                if (
                    not isinstance(exc, CircuitOpenError)
                    and not is_retryable_error(exc)
                ):
                    raise
                branch_errors.append("semantic")
                logger.warning(
                    "Semantic retrieval branch is unavailable.",
                    extra={"error_type": type(exc).__name__},
                )

        documents = self._fuse_rankings(result_groups, top_k=top_k)
        branch_counts = {
            branch: len(results)
            for branch, results in result_groups.items()
        }
        candidate_count = (
            semantic_candidate_count
            + sum(
                count
                for branch, count in branch_counts.items()
                if branch != "semantic"
            )
        )
        return RetrievalResult(
            documents=documents,
            candidate_count=candidate_count,
            accepted_count=len(documents),
            filter_match_count=filter_match_count,
            branch_counts=branch_counts,
            branch_errors=branch_errors,
        )

    def _semantic_search(
        self,
        query: str,
        top_k: int,
        district_filter: Optional[str],
        category_filter: Optional[str],
        price_min_filter: Optional[int],
        price_max_filter: Optional[int],
        open_at_filter: Optional[str],
        min_score: float,
        collection_name: Optional[str],
    ) -> tuple[List[Dict[str, Any]], int]:
        """Search the existing dense Qdrant branch."""

        query_vector = self.model.encode(query).tolist()
        search_filter = self._build_filter(
            district=district_filter,
            domain="food",
            category=category_filter,
            price_min=price_min_filter,
            price_max=price_max_filter,
        )

        candidate_limit = min(max(top_k * 2, 40), 80)
        raw_results = call_with_retry(
            lambda: self.client.search(
                collection_name=collection_name or self.collection_name,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=candidate_limit,
                with_payload=True,
                score_threshold=min_score,
            ),
            attempts=1,
            base_seconds=self.retry_base_seconds,
            max_seconds=self.retry_max_seconds,
            circuit_breaker=self.circuit_breaker,
        )

        documents = []
        for hit in raw_results:
            semantic_score = float(hit.score)
            document = self._to_document(hit.payload or {}, semantic_score)
            if not self._matches_structured_filters(
                document,
                price_min_filter=price_min_filter,
                price_max_filter=price_max_filter,
                open_at_filter=open_at_filter,
            ):
                continue
            title_match_score = field_match_score(
                query,
                document["title"],
            )
            address_match_score = field_match_score(
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
            document["semantic_score"] = semantic_score
            document["retrieval_sources"] = ["semantic"]
            documents.append(document)

        documents.sort(
            key=lambda document: (
                document["ranking_score"],
                document["score"],
            ),
            reverse=True,
        )
        return self._group_by_parent(documents)[:top_k], len(raw_results)

    @staticmethod
    def _matches_structured_filters(
        document: Dict[str, Any],
        *,
        price_min_filter: Optional[int],
        price_max_filter: Optional[int],
        open_at_filter: Optional[str],
    ) -> bool:
        # A restaurant matches when its available price range overlaps the
        # range requested by the user.
        if price_min_filter is not None:
            document_price_max = document.get("price_max")
            if (
                not isinstance(document_price_max, int)
                or document_price_max < price_min_filter
            ):
                return False

        if price_max_filter is not None:
            document_price_min = document.get("price_min")
            if (
                not isinstance(document_price_min, int)
                or document_price_min > price_max_filter
            ):
                return False

        if open_at_filter and not is_open_at(
            document.get("opening_intervals"),
            open_at_filter,
        ):
            return False

        return True

    def _validate_knowledge_versions(
        self,
        semantic_documents: List[Dict[str, Any]],
    ) -> None:
        lexical_index = getattr(self, "lexical_index", None)
        expected_version = getattr(
            lexical_index,
            "knowledge_version",
            None,
        )
        if not expected_version or not semantic_documents:
            return

        semantic_versions = {
            str(document.get("knowledge_version") or "").strip()
            for document in semantic_documents
        }
        if semantic_versions != {expected_version}:
            raise RetrievalConfigurationError(
                "Lexical and semantic indexes use different knowledge versions."
            )

    @staticmethod
    def _load_lexical_index(path: Path) -> Optional[LexicalIndex]:
        try:
            index = LexicalIndex.from_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Lexical food index is unavailable; semantic fallback remains active.",
                extra={"error_type": type(exc).__name__},
            )
            return None

        logger.info(
            "Lexical food index loaded.",
            extra={"entity_count": len(index.documents)},
        )
        return index

    @staticmethod
    def _fuse_rankings(
        result_groups: Dict[str, List[Dict[str, Any]]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Fuse branch ranks with RRF so incompatible raw scores are not added."""
        branch_weights = {
            "exact": 2.0,
            "keyword": 1.0,
            "semantic": 1.0,
        }
        fused: Dict[str, Dict[str, Any]] = {}

        for branch, documents in result_groups.items():
            weight = branch_weights[branch]
            for rank, document in enumerate(documents, start=1):
                parent_id = str(
                    document.get("parent_id")
                    or document.get("chunk_id")
                    or f"{branch}:{rank}"
                )
                existing = fused.get(parent_id)
                if existing is None:
                    existing = document.copy()
                    existing["retrieval_sources"] = []
                    existing["ranking_score"] = 0.0
                    fused[parent_id] = existing

                existing["ranking_score"] += weight / (RRF_K + rank)
                if branch not in existing["retrieval_sources"]:
                    existing["retrieval_sources"].append(branch)

                for score_name in (
                    "semantic_score",
                    "keyword_score",
                    "keyword_coverage",
                    "exact_score",
                    "match_score",
                ):
                    existing[score_name] = max(
                        float(existing.get(score_name, 0.0) or 0.0),
                        float(document.get(score_name, 0.0) or 0.0),
                    )
                existing["score"] = existing["semantic_score"]

                candidate_content = document.get("content", "")
                if len(candidate_content) > len(existing.get("content", "")):
                    existing["content"] = candidate_content
                    existing["text"] = candidate_content
                    existing["chunk_ids"] = document.get("chunk_ids", [])

        results = list(fused.values())
        for document in results:
            document["ranking_score"] = round(
                document["ranking_score"],
                8,
            )

        results.sort(
            key=lambda document: (
                document["ranking_score"],
                document.get("exact_score", 0.0),
                document.get("semantic_score", 0.0),
                document.get("keyword_score", 0.0),
            ),
            reverse=True,
        )
        return results[:top_k]

    def check_ready(self) -> None:
        self.client.get_collection(self.collection_name)
        lexical_index = getattr(self, "lexical_index", None)
        expected_version = getattr(
            lexical_index,
            "knowledge_version",
            None,
        )
        if not expected_version:
            return

        records, _ = self.client.scroll(
            collection_name=self.collection_name,
            limit=1,
            with_payload=["knowledge_version"],
            with_vectors=False,
        )
        if not records:
            raise RetrievalConfigurationError(
                "Qdrant collection does not contain any food document."
            )
        self._validate_knowledge_versions(
            [
                {
                    "knowledge_version": (
                        record.payload or {}
                    ).get("knowledge_version")
                }
                for record in records
            ]
        )

    def close(self) -> None:
        client = getattr(self, "client", None)
        if client is not None:
            client.close()

    @staticmethod
    def _build_filter(
        district: Optional[str],
        domain: Optional[str],
        category: Optional[str],
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
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

        if price_max is not None:
            conditions.append(
                FieldCondition(
                    key="price_min",
                    range=Range(lte=price_max),
                )
            )

        if price_min is not None:
            conditions.append(
                FieldCondition(
                    key="price_max",
                    range=Range(gte=price_min),
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
        price_data = parse_price_range(value("price_range"))
        opening_data = parse_opening_hours(value("opening_hours"))

        return {
            "score": score,
            "chunk_id": value("chunk_id"),
            "chunk_index": value("chunk_index", 0),
            "parent_id": value("parent_id"),
            "domain": value("domain"),
            "knowledge_version": value("knowledge_version"),
            "title": value("title"),
            "address": value("address"),
            "district": district,
            "district_normalized": (
                value("district_normalized") or normalize_text(district)
            ),
            "category": value("category"),
            "sub_category": value("sub_category"),
            "price_range": value("price_range"),
            "price_min": value("price_min", price_data["price_min"]),
            "price_max": value("price_max", price_data["price_max"]),
            "price_currency": value(
                "price_currency",
                price_data["price_currency"],
            ),
            "price_status": value(
                "price_status",
                price_data["price_status"],
            ),
            "opening_hours": value("opening_hours"),
            "opening_intervals": value(
                "opening_intervals",
                opening_data["opening_intervals"],
            ),
            "opening_status": value(
                "opening_status",
                opening_data["opening_status"],
            ),
            "opening_schedule_scope": value(
                "opening_schedule_scope",
                opening_data["opening_schedule_scope"],
            ),
            "tags": value("tags", []),
            "source_name": value("source_name", None),
            "source_url": value("source_url", None),
            "retrieved_at": value("retrieved_at", None),
            "last_verified_at": value("last_verified_at", None),
            "license": value("license", None),
            "verification_status": value(
                "verification_status",
                "unknown",
            ),
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
        return field_match_score(query, field_value)
