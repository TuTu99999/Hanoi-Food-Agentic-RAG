from __future__ import annotations

import os
from typing import Any, Callable

from sentence_transformers import SentenceTransformer


DEFAULT_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


def warm_model_cache(
    model_name: str,
    *,
    loader: Callable[..., Any] = SentenceTransformer,
) -> bool:
    """Ensure the embedding model exists locally.

    Returns True when a download was required and False on a cache hit.
    """
    try:
        loader(
            model_name,
            device="cpu",
            local_files_only=True,
        )
        return False
    except OSError:
        loader(
            model_name,
            device="cpu",
            local_files_only=False,
        )
        return True


def main() -> None:
    model_name = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL).strip()
    if not model_name:
        raise ValueError("EMBEDDING_MODEL must not be empty.")

    downloaded = warm_model_cache(model_name)
    status = "downloaded" if downloaded else "cache-hit"
    print(f"Embedding model ready: {model_name} ({status})")


if __name__ == "__main__":
    main()
