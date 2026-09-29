"""Test helpers for MCP tools."""


def unwrap_tool(tool):
    """Return the implementation callable across FastMCP 2-4."""
    return getattr(tool, "fn", tool)
