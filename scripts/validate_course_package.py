import argparse
import json

from courses.package import CoursePackageError, load_course_package
from courses.naming import graph_namespace_for, vector_alias_for


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one political-theory Course Package."
    )
    parser.add_argument("package_path")
    arguments = parser.parse_args()

    try:
        result = load_course_package(arguments.package_path)
    except CoursePackageError as exc:
        parser.error(str(exc))

    manifest = result.manifest
    print(
        json.dumps(
            {
                "valid": True,
                "course_id": manifest.course_id,
                "version": manifest.version,
                "documents": len(result.documents),
                "vector_alias": vector_alias_for(manifest.course_id),
                "graph_namespace": graph_namespace_for(
                    manifest.course_id,
                    manifest.version,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
