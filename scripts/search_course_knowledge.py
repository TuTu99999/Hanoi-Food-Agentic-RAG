import argparse
import json
import os

from academic_retrieval.service import (
    AcademicHybridRetriever,
    AcademicRetrievalError,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one grounded hybrid search against a course index."
    )
    parser.add_argument("processed_directory")
    parser.add_argument("indexed_directory")
    parser.add_argument("course_id")
    parser.add_argument("query")
    parser.add_argument("--course-version")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-dense-score", type=float, default=0.25)
    parser.add_argument("--document-id")
    parser.add_argument(
        "--mode",
        choices=("hybrid", "dense", "keyword"),
        default="hybrid",
    )
    parser.add_argument(
        "--qdrant-url",
        default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
    )
    parser.add_argument("--api-key", default=os.getenv("QDRANT_API_KEY") or None)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--collection")
    arguments = parser.parse_args()

    modes = {
        "hybrid": ("dense", "keyword"),
        "dense": ("dense",),
        "keyword": ("keyword",),
    }[arguments.mode]
    retriever = None
    try:
        retriever = AcademicHybridRetriever.from_artifacts(
            arguments.processed_directory,
            arguments.indexed_directory,
            qdrant_url=arguments.qdrant_url,
            qdrant_api_key=arguments.api_key,
            local_files_only=not arguments.allow_download,
            collection_name=arguments.collection,
        )
        result = retriever.search(
            arguments.query,
            course_id=arguments.course_id,
            course_version=arguments.course_version,
            top_k=arguments.top_k,
            min_dense_score=arguments.min_dense_score,
            document_id=arguments.document_id,
            modes=modes,
        )
    except (AcademicRetrievalError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    finally:
        if retriever is not None:
            retriever.close()

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
