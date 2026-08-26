import argparse
import json
import os
from pathlib import Path

from academic_retrieval.evaluation import (
    evaluate_academic_retrieval,
    load_retrieval_cases,
)
from academic_retrieval.service import (
    AcademicHybridRetriever,
    AcademicRetrievalError,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate course retrieval with Recall@k, MRR and safety metrics."
    )
    parser.add_argument("processed_directory")
    parser.add_argument("indexed_directory")
    parser.add_argument("cases_path")
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
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    modes = {
        "hybrid": ("dense", "keyword"),
        "dense": ("dense",),
        "keyword": ("keyword",),
    }[arguments.mode]
    retriever = None
    try:
        cases = load_retrieval_cases(arguments.cases_path)
        retriever = AcademicHybridRetriever.from_artifacts(
            arguments.processed_directory,
            arguments.indexed_directory,
            qdrant_url=arguments.qdrant_url,
            qdrant_api_key=arguments.api_key,
            local_files_only=not arguments.allow_download,
            collection_name=arguments.collection,
        )
        report = evaluate_academic_retrieval(
            retriever,
            cases,
            modes=modes,
        )
    except (AcademicRetrievalError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    finally:
        if retriever is not None:
            retriever.close()

    serialized_report = report.model_dump(mode="json")
    if arguments.output:
        output_path = arguments.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(serialized_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(serialized_report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
