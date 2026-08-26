from typing import Any

from mcp.server import MCPServer


EXPECTED_TOOLS = {
    "ask_course_knowledge",
    "start_assessment",
    "submit_assessment",
    "get_course_mastery",
    "create_learning_plan",
    "approve_learning_plan",
    "get_current_learning_plan",
    "list_learning_events",
}
EXPECTED_READ_ONLY_TOOLS = {
    "ask_course_knowledge",
    "get_course_mastery",
    "get_current_learning_plan",
    "list_learning_events",
}


async def evaluate_mcp_contract(server: MCPServer) -> dict[str, Any]:
    tools = await server.list_tools()
    tool_by_name = {tool.name: tool for tool in tools}
    discovered = set(tool_by_name)
    covered = len(discovered & EXPECTED_TOOLS)
    structured = sum(
        bool(tool.output_schema)
        for tool in tool_by_name.values()
        if tool.name in EXPECTED_TOOLS
    )
    user_id_exposure_count = sum(
        "user_id" in tool.input_schema.get("properties", {})
        for tool in tools
    )
    annotation_matches = sum(
        bool(tool.annotations and tool.annotations.read_only_hint)
        == (name in EXPECTED_READ_ONLY_TOOLS)
        for name, tool in tool_by_name.items()
        if name in EXPECTED_TOOLS
    )
    approval = tool_by_name.get("approve_learning_plan")
    confirmation_schema = (
        approval.input_schema.get("properties", {}).get("confirmation", {})
        if approval is not None
        else {}
    )
    approval_guard = confirmation_schema.get("const") == "APPROVE"
    count = len(EXPECTED_TOOLS)
    return {
        "expected_tool_count": count,
        "actual_tool_count": len(tools),
        "tool_coverage_rate": round(covered / count, 6),
        "structured_output_rate": round(structured / count, 6),
        "annotation_accuracy": round(annotation_matches / count, 6),
        "identity_argument_exposure_count": user_id_exposure_count,
        "human_approval_guard": approval_guard,
        "missing_tools": sorted(EXPECTED_TOOLS - discovered),
        "unexpected_tools": sorted(discovered - EXPECTED_TOOLS),
    }


__all__ = ["EXPECTED_TOOLS", "evaluate_mcp_contract"]
