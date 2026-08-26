import re


def vector_alias_for(course_id: str) -> str:
    return f"course_{course_id}_current"


def vector_collection_for(
    course_id: str,
    version: str,
    knowledge_version: str,
) -> str:
    """Return an immutable physical collection name for one knowledge build."""

    safe_version = re.sub(r"[^a-zA-Z0-9]+", "_", version).strip("_")
    safe_knowledge = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        knowledge_version,
    ).strip("_")
    knowledge_suffix = safe_knowledge[-12:]
    return f"course_{course_id}_{safe_version}_{knowledge_suffix}"


def graph_namespace_for(course_id: str, version: str) -> str:
    safe_version = re.sub(r"[^a-zA-Z0-9]+", "_", version).strip("_")
    return f"{course_id}:{safe_version}"
