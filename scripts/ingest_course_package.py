import argparse
import json

from ingestion.service import (
    CourseIngestionConfig,
    CourseIngestionError,
    ingest_course_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse and chunk one political-theory Course Package."
    )
    parser.add_argument("package_path")
    parser.add_argument("--output-root", default="data/courses")
    parser.add_argument("--max-words", type=int, default=220)
    parser.add_argument("--overlap-words", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args()

    try:
        result = ingest_course_package(
            arguments.package_path,
            output_root=arguments.output_root,
            config=CourseIngestionConfig(
                max_words=arguments.max_words,
                overlap_words=arguments.overlap_words,
            ),
            dry_run=arguments.dry_run,
            force=arguments.force,
        )
    except (CourseIngestionError, ValueError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            {
                "course_id": result.manifest.course_id,
                "course_version": result.manifest.course_version,
                "knowledge_version": result.manifest.knowledge_version,
                "documents": result.manifest.document_count,
                "sections": result.manifest.section_count,
                "chunks": result.manifest.chunk_count,
                "question_bank": (
                    str(result.question_bank_path)
                    if result.question_bank_path is not None
                    else None
                ),
                "learning_map": (
                    str(result.learning_map_path)
                    if result.learning_map_path is not None
                    else None
                ),
                "dry_run": result.dry_run,
                "output_directory": str(result.output_directory),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
