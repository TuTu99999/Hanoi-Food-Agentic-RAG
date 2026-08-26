import math
from collections import Counter
from dataclasses import dataclass

from embedding.text_utils import lexical_terms
from schemas.ingestion import AcademicChunk


@dataclass(frozen=True)
class AcademicLexicalMatch:
    chunk: AcademicChunk
    score: float


class AcademicLexicalIndex:
    """Small in-memory BM25 index for one course knowledge version."""

    def __init__(self, chunks: list[AcademicChunk] | tuple[AcademicChunk, ...]):
        if not chunks:
            raise ValueError("AcademicLexicalIndex cần ít nhất một chunk.")

        self.chunks = tuple(chunks)
        first = self.chunks[0]
        self.course_id = first.course_id
        self.course_version = first.course_version
        self.knowledge_version = first.knowledge_version
        for chunk in self.chunks:
            if (
                chunk.course_id != self.course_id
                or chunk.course_version != self.course_version
                or chunk.knowledge_version != self.knowledge_version
            ):
                raise ValueError(
                    "Lexical index không được trộn môn hoặc knowledge version."
                )

        self._document_terms = [
            self._terms_for_chunk(chunk)
            for chunk in self.chunks
        ]
        self._document_lengths = [len(terms) for terms in self._document_terms]
        self._average_document_length = (
            sum(self._document_lengths) / len(self._document_lengths)
        )
        self._document_frequencies = self._build_document_frequencies()

    @staticmethod
    def _terms_for_chunk(chunk: AcademicChunk) -> list[str]:
        document_terms = lexical_terms(chunk.citation.document_title)
        section_terms = lexical_terms(chunk.citation.section_title or "")
        content_terms = lexical_terms(chunk.content)
        return [
            *document_terms,
            *document_terms,
            *section_terms,
            *section_terms,
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
        document_count = len(self.chunks)
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
                    + b * document_length / self._average_document_length
                )
            )
            score += inverse_document_frequency * (
                term_frequency * (k1 + 1) / denominator
            )
        return score

    def search(
        self,
        query: str,
        *,
        limit: int = 15,
        document_id: str | None = None,
    ) -> list[AcademicLexicalMatch]:
        if limit <= 0:
            raise ValueError("limit phải lớn hơn 0.")
        query_terms = lexical_terms(query)
        if not query_terms:
            return []

        matches = []
        for index, chunk in enumerate(self.chunks):
            if document_id and chunk.document_id != document_id:
                continue
            score = self._bm25_score(query_terms, index)
            if score > 0:
                matches.append(AcademicLexicalMatch(chunk=chunk, score=score))
        matches.sort(key=lambda match: match.score, reverse=True)
        return matches[:limit]
