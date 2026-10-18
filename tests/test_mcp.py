import asyncio
from backend.mcp_server import mcp


def test_mcp_preserves_original_tools_and_adds_repository_investigation():
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {"history", "localize", "impact", "experts", "similar_issues", "triage", "search_code", "search_commits", "investigate", "read_source", "get_symbol_context", "trace_callers", "trace_callees"}
    triage = next(tool for tool in tools if tool.name == "triage")
    assert triage.inputSchema["properties"]["post"]["default"] is False
