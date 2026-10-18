"""Repository-aware read tools and explicit guarded triage actions."""
import logging
from mcp.server.fastmcp import FastMCP
from backend.api.routes import graph, get_graph
from backend.tools.history import history as run_history
from backend.tools.localize import localize as run_localize
from backend.tools.impact import impact as run_impact
from backend.tools.experts import experts as run_experts
from backend.tools.similar import similar_issues as run_similar
from backend.tools.triage import triage as run_triage
from backend.agent.investigation import investigate as run_investigation, search_code as run_search_code, search_commits as run_search_commits

logging.basicConfig(level=logging.INFO)
mcp = FastMCP("WhyGraph")


@mcp.tool()
def search_code(repo_id: str, query: str, limit: int = 6, as_of: str | None = None) -> dict:
    """Search current source symbols in an explicitly selected indexed repository."""
    result = run_search_code(repo_id, query, limit, as_of)
    compact = {"repository_id": result["repository_id"], "revision": result["revision"], "results": [{
        **{key: item[key] for key in ("evidence_id", "repository_id", "evidence_type", "source_url", "file_path", "commit_sha", "start_line", "end_line", "excerpt", "symbol_id", "relationship", "score", "vector_similarity")},
        "symbol": {key: item["symbol"].get(key) for key in ("id", "qualified_name", "name", "kind", "file_path", "start_line", "end_line")},
    } for item in result["results"]]}
    logging.getLogger("whygraph.mcp").info("search_code returned %s verified spans", len(compact["results"]))
    return compact


@mcp.tool()
def search_commits(repo_id: str, query: str, as_of: str | None = None, limit: int = 10) -> list[dict]:
    """Search commit messages in the explicitly selected repository and temporal window."""
    return run_search_commits(repo_id, query, as_of, limit)


@mcp.tool()
def investigate(repo_id: str, query: str, conversation_id: str | None = None, as_of: str | None = None, context: str = "") -> dict:
    """Investigate repository source, callers/callees, and function history with verified citations."""
    return run_investigation(repo_id, query, conversation_id, as_of, context)


@mcp.tool()
def history(symbol: str, as_of: str | None = None, repo_id: str | None = None) -> dict:
    """What changed, when, why, and the exact source URLs for a Python symbol."""
    return run_history(get_graph(repo_id), symbol, as_of)


@mcp.tool()
def impact(symbol: str, as_of: str | None = None, repo_id: str | None = None) -> dict:
    """Reverse CALLS traversal to depth three, with evidence paths."""
    return run_impact(get_graph(repo_id), symbol, as_of)


@mcp.tool()
def experts(path_or_symbol: str, as_of: str | None = None, repo_id: str | None = None) -> dict:
    """Rank developers using source-backed changes, fixes and reviews."""
    return run_experts(get_graph(repo_id), path_or_symbol, as_of)


@mcp.tool()
def similar_issues(text: str, as_of: str | None = None, repo_id: str | None = None) -> dict:
    """Retrieve historical issues from FalkorDB's semantic vector index."""
    return run_similar(get_graph(repo_id), text, as_of)


@mcp.tool()
def localize(title: str, body: str = "", created_at: str | None = None, as_of: str | None = None, repo_id: str | None = None) -> dict:
    """Rank candidate functions using historical issue/PR/commit graph paths."""
    return run_localize(get_graph(repo_id), {"title": title, "body": body, "created_at": created_at}, as_of)


@mcp.tool()
def triage(title: str = "", body: str = "", issue_number: int | None = None, post: bool = False, as_of: str | None = None, preview_id: str | None = None, repo_id: str | None = None) -> dict:
    """Preview graph recommendations. To post the exact reviewed comment to your verified fork, pass post=true and the returned preview_id."""
    if repo_id not in (None, "default"):
        if post or issue_number or preview_id:
            raise ValueError("Numbered previews and posting are limited to the default repository")
        from backend.agent.workflow import analyze
        from backend.tools.triage import render
        result = analyze(get_graph(repo_id), {"title": title, "body": body}, as_of)
        return {**result, "markdown": render(result), "action": {"posted": False, "mode": "preview"}}
    if post and (issue_number is None or not preview_id):
        raise ValueError("Posting requires an existing issue_number and its preview_id")
    return run_triage(graph(), issue_number if issue_number else {"title": title, "body": body}, post=post, as_of=as_of, preview_id=preview_id)


@mcp.tool()
def read_source(repo_id: str, file_path: str, start_line: int = 1, end_line: int | None = None, as_of: str | None = None) -> dict:
    """Read a bounded, revision-pinned source span from the selected repository."""
    from backend.agent.toolbox import dispatch
    return dispatch(repo_id, as_of, "read_source", {"file_path": file_path, "start_line": start_line, "end_line": end_line})


@mcp.tool()
def get_symbol_context(repo_id: str, symbol: str, as_of: str | None = None) -> dict:
    """Read snapshot metadata and statically resolved callers and callees."""
    from backend.agent.toolbox import dispatch
    return dispatch(repo_id, as_of, "get_symbol_context", {"symbol": symbol})


@mcp.tool()
def trace_callers(repo_id: str, symbol: str, as_of: str | None = None) -> dict:
    """Trace bounded static callers within the selected repository snapshot."""
    from backend.agent.toolbox import dispatch
    return dispatch(repo_id, as_of, "trace_callers", {"symbol": symbol})


@mcp.tool()
def trace_callees(repo_id: str, symbol: str, as_of: str | None = None) -> dict:
    """Trace bounded static callees within the selected repository snapshot."""
    from backend.agent.toolbox import dispatch
    return dispatch(repo_id, as_of, "trace_callees", {"symbol": symbol})


if __name__ == "__main__":
    mcp.run(transport="stdio")
