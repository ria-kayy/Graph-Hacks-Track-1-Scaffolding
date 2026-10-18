import asyncio
import json
import os
import sys
import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from backend.config import ROOT
from backend.repositories import repositories


async def main():
    server = StdioServerParameters(command=sys.executable, args=["-m", "backend.mcp_server"], cwd=str(ROOT), env=os.environ.copy())
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "history", "localize", "impact", "experts", "similar_issues", "triage",
                "search_code", "search_commits", "investigate", "read_source", "get_symbol_context", "trace_callers", "trace_callees",
            }
            indexed = next((item for item in repositories() if item.get("indexed_ref")), None)
            if indexed is None:
                raise RuntimeError("Register and index a repository before running the MCP retrieval check")
            for name, arguments in [
                ("search_commits", {"repo_id": indexed["repository_id"], "query": "progress bar generator", "limit": 1}),
                ("search_code", {"repo_id": indexed["repository_id"], "query": "progress bar generator", "limit": 2}),
                ("investigate", {"repo_id": indexed["repository_id"], "query": "Where is the progress bar generator?"}),
            ]:
                with anyio.fail_after(45):
                    result = await session.call_tool(name, arguments)
                assert not result.isError, result.content
                assert result.content
                if name in ("search_code", "investigate"):
                    payload = result.structuredContent or json.loads(result.content[0].text)
                    payload = payload.get("result", payload)
                    evidence = payload.get("results", payload.get("evidence", []))
                    sources = [item for item in evidence if item.get("evidence_type") == "source"]
                    assert sources, "MCP must return actual source evidence, not just a successful call"
                    assert all(item["repository_id"] == indexed["repository_id"] and item["commit_sha"] == payload["revision"] for item in sources)
                print(f"MCP {name} passed", flush=True)
            print("MCP stdio handshake, thirteen tools, and all three repository retrieval calls passed")



if __name__ == "__main__":
    asyncio.run(main())
