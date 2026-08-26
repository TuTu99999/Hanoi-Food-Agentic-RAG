"""Stable root entry point for local MCP hosts using an absolute file path."""

from academic_mcp.server import mcp


if __name__ == "__main__":
    mcp.run(transport="stdio")
