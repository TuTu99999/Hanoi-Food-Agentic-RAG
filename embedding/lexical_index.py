import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from embedding.catalog_schema import (
    is_open_at,
    parse_opening_hours,
    parse_price_range,
)
from embedding.text_utils import (
    field_match_score,
    lexical_terms,
    normalize_text,
)


EXACT_MATCH_THRESHOLD = 0.84


class LexicalIndex:
    """Small in-memory exact-name and BM25 index for the food catalog."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.documents = self._group_entities(rows)
        if not self.documents:
            raise ValueError("Food catalog does not contain any valid document.")

        self._document_terms = [
            self._build_document_terms(document)
            for document in self.documents
        ]
        self._document_lengths = [
            len(terms)
            for terms in self._document_terms
        ]
        self._average_document_length = (
            sum(self._document_lengths) / len(self._document_lengths)
        )
        self._document_frequencies = self._build_document_frequencies()

    @classmethod
    def from_json(cls, path: Path) -> "LexicalIndex":
        with path.open("r", encoding="utf-8") as file:
            rows = json.load(file)
        if not isinstance(rows, list):
            raise ValueError("Food catalog must contain a JSON list.")
        return cls(rows)

    def count_matching_filters(
        self,
        district: str | None = None,
        category: str | None = None,
        price_max: int | None = None,
        open_at: str | None = None,
    ) -> int:
        return sum(
            1
            for document in self.documents
            if self._matches_filters(
                document,
                district,
                category,
                price_max,
                open_at,
            )
        )

    def exact_search(
        self,
        query: str,
        district: str | None = None,
        category: str | None = None,
        price_max: int | None = None,
        open_at: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        matches = []
        for document in self.documents:
            if not self._matches_filters(
                document,
                district,
                category,
                price_max,
                open_at,
            ):
                continue

            exact_score = field_match_score(query, document["title"])
            if exact_score < EXACT_MATCH_THRESHOLD:
                continue

            result = self._public_document(document)
            result["exact_score"] = round(exact_score, 6)
            result["match_score"] = round(exact_score, 6)
            result["retrieval_sources"] = ["exact"]
            matches.append(result)

        matches.sort(
            key=lambda document: (
                document["exact_score"],
                field_match_score(query, document["address"]),
            ),
            reverse=True,
        )
        return matches[:limit]

    def keyword_search(
        self,
        query: str,
        district: str | None = None,
        category: str | None = None,
        price_max: int | None = None,
        open_at: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query_terms = lexical_terms(query)
        if not query_terms:
            return []

        query_unigrams = {
            term
            for term in query_terms
            if "_" not in term
        }
        results = []
        for index, document in enumerate(self.documents):
            if not self._matches_filters(
                document,
                district,
                category,
                price_max,
                open_at,
            ):
                continue

            score = self._bm25_score(query_terms, index)
            if score <= 0:
                continue

            document_unigrams = set(
                term
                for term in self._document_terms[index]
                if "_" not in term
            )
            coverage = (
                len(query_unigrams.intersection(document_unigrams))
                / len(query_unigrams)
                if query_unigrams
                else 0.0
            )

            result = self._public_document(document)
            result["keyword_score"] = round(score, 6)
            result["keyword_coverage"] = round(coverage, 6)
            result["retrieval_sources"] = ["keyword"]
            results.append(result)

        results.sort(
            key=lambda document: (
                document["keyword_score"],
                document["keyword_coverage"],
            ),
            reverse=True,
        )
        return results[:limit]

    @staticmethod
    def _group_entities(
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            if normalize_text(row.get("domain")) != "food":
                continue
            if normalize_text(row.get("category")) != "am thuc":
                continue

            parent_id = str(row.get("parent_id") or row.get("id") or "").strip()
            if not parent_id:
                continue

            document = grouped.get(parent_id)
            if document is None:
                title = str(row.get("title") or "").strip()
                address = str(row.get("address") or "").strip()
                district = str(row.get("district") or "").strip()
                category = str(row.get("category") or "").strip()
                sub_category = str(row.get("sub_category") or "").strip()
                tags = [
                    str(tag).strip()
                    for tag in row.get("tags", [])
                    if str(tag).strip()
                ]
                price_data = parse_price_range(row.get("price_range"))
                opening_data = parse_opening_hours(row.get("opening_hours"))
                document = {
                    "score": 0.0,
                    "semantic_score": 0.0,
                    "keyword_score": 0.0,
                    "keyword_coverage": 0.0,
                    "exact_score": 0.0,
                    "match_score": 0.0,
                    "ranking_score": 0.0,
                    "parent_id": parent_id,
                    "domain": "food",
                    "title": title,
                    "title_normalized": (
                        row.get("title_normalized") or normalize_text(title)
                    ),
                    "address": address,
                    "address_normalized": (
                        row.get("address_normalized") or normalize_text(address)
                    ),
                    "district": district,
                    "district_normalized": (
                        row.get("district_normalized")
                        or normalize_text(district)
                    ),
                    "category": category,
                    "category_normalized": (
                        row.get("category_normalized")
                        or normalize_text(category)
                    ),
                    "sub_category": sub_category,
                    "sub_category_normalized": (
                        row.get("sub_category_normalized")
                        or normalize_text(sub_category)
                    ),
                    "price_range": row.get("price_range", ""),
                    "price_min": row.get(
                        "price_min",
                        price_data["price_min"],
                    ),
                    "price_max": row.get(
                        "price_max",
                        price_data["price_max"],
                    ),
                    "price_currency": row.get(
                        "price_currency",
                        price_data["price_currency"],
                    ),
                    "price_status": row.get(
                        "price_status",
                        price_data["price_status"],
                    ),
                    "opening_hours": row.get("opening_hours", ""),
                    "opening_intervals": row.get(
                        "opening_intervals",
                        opening_data["opening_intervals"],
                    ),
                    "opening_status": row.get(
                        "opening_status",
                        opening_data["opening_status"],
                    ),
                    "opening_schedule_scope": row.get(
                        "opening_schedule_scope",
                        opening_data["opening_schedule_scope"],
                    ),
                    "tags": tags,
                    "tags_normalized": (
                        row.get("tags_normalized")
                        or [normalize_text(tag) for tag in tags]
                    ),
                    "_chunks": [],
                }
                grouped[parent_id] = document

            chunk_id = row.get("chunk_id")
            description = str(
                row.get("description")
                or row.get("content")
                or ""
            ).strip()
            document["_chunks"].append(
                (
                    int(row.get("chunk_index", 0) or 0),
                    chunk_id,
                    description,
                )
            )

        documents = []
        for document in grouped.values():
            chunks = sorted(document.pop("_chunks"))
            document["chunk_id"] = chunks[0][1] if chunks else ""
            document["chunk_ids"] = [
                chunk_id
                for _, chunk_id, _ in chunks
                if chunk_id
            ]
            descriptions = []
            for _, _, description in chunks:
                if description and description not in descriptions:
                    descriptions.append(description)
            content = "\n\n".join(descriptions)
            document["content"] = content
            document["text"] = content
            documents.append(document)

        return documents

    @staticmethod
    def _build_document_terms(document: dict[str, Any]) -> list[str]:
        title_terms = lexical_terms(document["title"])
        address_terms = lexical_terms(document["address"])
        facet_text = " ".join(
            [
                document["district"],
                document["sub_category"],
                *document["tags"],
            ]
        )
        facet_terms = lexical_terms(facet_text)
        content_terms = lexical_terms(document["content"])
        return [
            *title_terms,
            *title_terms,
            *title_terms,
            *address_terms,
            *address_terms,
            *facet_terms,
            *facet_terms,
            *content_terms,
        ]

    def _build_document_frequencies(self) -> Counter:
        frequencies: Counter = Counter()
        for terms in self._document_terms:
            frequencies.update(set(terms))
        return frequencies

    def _bm25_score(self, query_terms: list[str], document_index: int) -> float:
        k1 = 1.5
        b = 0.75
        terms = self._document_terms[document_index]
        frequencies = Counter(terms)
        document_length = self._document_lengths[document_index]
        document_count = len(self.documents)
        score = 0.0

        for term in set(query_terms):
            term_frequency = frequencies.get(term, 0)
            if not term_frequency:
                continue

            document_frequency = self._document_frequencies[term]
            inverse_document_frequency = math.log(
                1
                + (
                    document_count
                    - document_frequency
                    + 0.5
                )
                / (document_frequency + 0.5)
            )
            denominator = term_frequency + (
                k1
                * (
                    1
                    - b
                    + (
                        b
                        * document_length
                        / self._average_document_length
                    )
                )
            )
            score += inverse_document_frequency * (
                term_frequency * (k1 + 1) / denominator
            )

        return score

    @staticmethod
    def _public_document(document: dict[str, Any]) -> dict[str, Any]:
        return document.copy()

    @staticmethod
    def _matches_filters(
        document: dict[str, Any],
        district: str | None,
        category: str | None,
        price_max: int | None,
        open_at: str | None,
    ) -> bool:
        normalized_district = normalize_text(district)
        if (
            normalized_district
            and document["district_normalized"] != normalized_district
        ):
            return False

        normalized_category = normalize_text(category)
        if normalized_category:
            category_values = {
                document["category_normalized"],
                document["sub_category_normalized"],
                *document["tags_normalized"],
            }
            if not any(
                normalized_category == value
                or normalized_category in value
                or value in normalized_category
                for value in category_values
                if value
            ):
                return False

        if price_max is not None:
            document_price_max = document.get("price_max")
            if (
                not isinstance(document_price_max, int)
                or document_price_max > price_max
            ):
                return False

        if open_at and not is_open_at(
            document.get("opening_intervals"),
            open_at,
        ):
            return False

        return True
