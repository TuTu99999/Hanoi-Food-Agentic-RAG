import argparse
import json
import os

from academic_retrieval.artifacts import (
    CourseArtifactError,
    build_course_embeddings,
    load_processed_course,
)


DEFAULT_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build versioned embeddings from one processed Course Package."
    )
    parser.add_argument("processed_directory")
    parser.add_argument("--output-directory")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow SentenceTransformer to download a missing model.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate processed artifacts without loading the model.",
    )
    arguments = parser.parse_args()

    try:
        if arguments.dry_run:
            processed = load_processed_course(arguments.processed_directory)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "course_id": processed.manifest.course_id,
                        "course_version": processed.manifest.course_version,
                        "knowledge_version": processed.manifest.knowledge_version,
                        "chunks": len(processed.chunks),
                        "model_loaded": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        result = build_course_embeddings(
            arguments.processed_directory,
            output_directory=arguments.output_directory,
            model_name=arguments.model,
            batch_size=arguments.batch_size,
            local_files_only=not arguments.allow_download,
            force=arguments.force,
        )
    except (CourseArtifactError, ValueError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            {
                "course_id": result.manifest.course_id,
                "course_version": result.manifest.course_version,
                "knowledge_version": result.manifest.knowledge_version,
                "embedding_model": result.manifest.embedding_model,
                "vector_dimension": result.manifest.vector_dimension,
                "points": result.manifest.point_count,
                "output_directory": str(result.output_directory),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
