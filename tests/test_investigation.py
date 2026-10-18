from types import SimpleNamespace

from backend.agent import investigation


def test_retrieval_only_investigation_keeps_verified_source_and_history_separate(monkeypatch):
    repo_id = "repo-a"
    symbol = {"id": "owner/repo:src.py:pkg.run", "qualified_name": "pkg.run", "name": "run", "kind": "function", "file_path": "src.py", "start_line": 4}
    source = {"evidence_id": "source-1", "repository_id": repo_id, "evidence_type": "source", "source_url": "https://github.com/owner/repo/blob/abc/src.py#L4-L8", "file_path": "src.py", "commit_sha": "abc", "start_line": 4, "end_line": 8, "excerpt": "4: def run():", "symbol_id": symbol["id"], "score": 2, "symbol": symbol}
    commit = {"sha": "def", "url": "https://github.com/owner/repo/commit/def", "timestamp": "2020-01-01T00:00:00Z", "message": "historical run change"}
    monkeypatch.setattr(investigation, "get_repository", lambda _id: {"repository_id": repo_id, "identity": "owner/repo"})
    monkeypatch.setattr(investigation, "context", lambda _id: SimpleNamespace(graph_name="graph-a"))
    monkeypatch.setattr(investigation, "Graph", lambda _name: object())
    monkeypatch.setattr(investigation, "search_code", lambda *a, **k: {"repository_id": repo_id, "revision": "abc", "results": [source]})
    monkeypatch.setattr(investigation, "search_commits", lambda *a, **k: [dict(commit)])
    monkeypatch.setattr(investigation, "symbol_context", lambda *a: {"callers": [], "callees": [], "snapshot_ref": "abc"})
    monkeypatch.setattr("backend.tools.history.history", lambda *a: {"symbol": symbol, "as_of": "2026-01-01T00:00:00Z", "timeline": [], "claims": [], "sources": [], "note": "No verified rationale was found."})
    monkeypatch.setattr("backend.tools.similar.similar_issues", lambda *a: [])
    monkeypatch.setattr(investigation, "properties", lambda value: value)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(investigation, "validate_evidence", lambda evidence, *args: (evidence, []))
    class Graph:
        def query(self, query, params=None):
            return [[{"id": "pr:706", "number": 706, "url": "https://github.com/owner/repo/pull/706"}, {"id": "issue:651", "number": 651, "url": "https://github.com/owner/repo/issues/651"}]] if "PullRequest" in query else [["pkg.run", "old.py"]]
    monkeypatch.setattr(investigation, "Graph", lambda _name: Graph())
    investigation._conversations.clear()
    result = investigation.investigate(repo_id, "why did run change?")
    historical = next(item for item in result["evidence"] if item["evidence_type"] == "commit")
    direct = next(item for item in result["evidence"] if item["evidence_type"] == "source")
    assert result["mode"] == "retrieval_only"
    assert direct["source_url"].endswith("src.py#L4-L8")
    assert historical["relationship"].endswith("background only")
    assert historical["verified_paths"][0]["pr"]["number"] == 706
    assert historical["verified_paths"][0]["issue"]["number"] == 651


def test_conversation_refuses_a_different_repository():
    investigation._conversations.clear()
    investigation._conversations["c"] = {"repository_id": "repo-a", "query": "retry", "symbols": []}
    try:
        investigation.investigate("repo-b", "why did it change?", "c")
    except ValueError as exc:
        assert "different repository" in str(exc)
    else:
        raise AssertionError("cross-repository context was accepted")
