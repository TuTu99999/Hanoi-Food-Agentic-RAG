import argparse
import json
import os

from academic_retrieval.artifacts import CourseArtifactError
from academic_retrieval.qdrant_store import (
    load_course_vector_artifact,
    upload_course_vectors,
)
from courses.naming import vector_alias_for, vector_collection_for


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload one immutable course vector artifact to Qdrant."
    )
    parser.add_argument("indexed_directory")
    parser.add_argument(
        "--qdrant-url",
        default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
    )
    parser.add_argument("--api-key", default=os.getenv("QDRANT_API_KEY") or None)
    parser.add_argument("--no-alias-switch", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate vector artifacts without contacting Qdrant.",
    )
    arguments = parser.parse_args()

    try:
        artifact = load_course_vector_artifact(arguments.indexed_directory)
        manifest = artifact.manifest
        if arguments.dry_run:
            print(
                json.dumps(
                    {
                        "valid": True,
                        "course_id": manifest.course_id,
                        "course_version": manifest.course_version,
                        "knowledge_version": manifest.knowledge_version,
                        "points": manifest.point_count,
                        "vector_dimension": manifest.vector_dimension,
                        "collection": vector_collection_for(
                            manifest.course_id,
                            manifest.course_version,
                            manifest.knowledge_version,
                        ),
                        "alias": vector_alias_for(manifest.course_id),
                        "qdrant_contacted": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=arguments.qdrant_url,
            api_key=arguments.api_key,
            timeout=60,
        )
        try:
            result = upload_course_vectors(
                client,
                artifact,
                switch_alias=not arguments.no_alias_switch,
            )
        finally:
            client.close()
    except (CourseArtifactError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            {
                "collection": result.collection_name,
                "alias": result.alias_name,
                "alias_switched": result.alias_switched,
                "points": result.point_count,
                "vector_dimension": result.vector_dimension,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
