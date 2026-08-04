from langsmith.wrappers import wrap_openai


def trace_inputs(inputs: dict) -> dict:
    history = inputs.get("history") or []
    return {
        "question": inputs.get("user_question"),
        "district": inputs.get("district"),
        "collection": inputs.get("collection_name"),
        "history_message_count": len(history),
    }


def trace_outputs(outputs: dict) -> dict:
    return {
        "answer": outputs.get("answer"),
        "evidence_count": len(outputs.get("context") or []),
        "prompt_tokens": outputs.get("prompt_tokens", 0),
        "completion_tokens": outputs.get("completion_tokens", 0),
        "latency_ms": outputs.get("latency_ms"),
    }


def reduce_stream(chunks: list[str]) -> dict:
    return {
        "answer": "".join(chunks),
        "chunk_count": len(chunks),
    }


def wrap_openai_if_enabled(client, enabled: bool):
    return wrap_openai(client) if enabled else client
