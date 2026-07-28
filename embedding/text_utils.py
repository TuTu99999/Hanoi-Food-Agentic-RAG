import re
import unicodedata
from difflib import SequenceMatcher


LEXICAL_STOP_WORDS = {
    "a",
    "ai",
    "bao",
    "cai",
    "cho",
    "co",
    "cua",
    "duoc",
    "giup",
    "ha",
    "hay",
    "hoi",
    "khong",
    "la",
    "minh",
    "mot",
    "muon",
    "nao",
    "nhe",
    "nhi",
    "noi",
    "o",
    "t",
    "tai",
    "tim",
    "toi",
    "va",
    "voi",
    "xin",
}


def normalize_text(value: str | None) -> str:
    """Normalize Vietnamese text for filters and lexical matching."""
    if not value:
        return ""

    normalized = unicodedata.normalize("NFD", value.casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = normalized.replace("đ", "d")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def field_match_score(query: str, field_value: str) -> float:
    """Return a typo-tolerant match score between a query and one field."""
    normalized_query = normalize_text(query)
    normalized_field = normalize_text(field_value)
    if not normalized_query or not normalized_field:
        return 0.0

    padded_query = f" {normalized_query} "
    padded_field = f" {normalized_field} "
    if padded_field in padded_query:
        return 1.0

    query_tokens = normalized_query.split()
    field_tokens = normalized_field.split()
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


def lexical_terms(value: str) -> list[str]:
    """Build lightweight Vietnamese unigram and adjacent-bigram terms."""
    words = [
        word
        for word in normalize_text(value).split()
        if word not in LEXICAL_STOP_WORDS
    ]
    bigrams = [
        f"{first}_{second}"
        for first, second in zip(words, words[1:])
    ]
    return [*words, *bigrams]
