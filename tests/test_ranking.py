from backend.tools.localize import score, WEIGHTS
import backend.tools.localize as localize_module


def test_weights_and_stronger_graph_evidence():
    assert sum(WEIGHTS.values()) == 1
    direct = dict.fromkeys(WEIGHTS, .5)
    direct["historical_fix_frequency"] = 1
    direct["graph_proximity"] = 1
    expanded = dict(direct, historical_fix_frequency=0, graph_proximity=.3)
    assert score(direct) > score(expanded)


def test_current_localization_uses_direct_code_without_historical_issue(monkeypatch):
    class Graph:
        name = "whygraph_repo"

    symbol = {"id": "owner/repo:pkg.py:pkg.retry", "qualified_name": "pkg.retry", "file_path": "pkg.py", "start_line": 3, "end_line": 5, "kind": "function"}
    monkeypatch.setattr(localize_module, "cutoff", lambda value: value or "2026-01-01T00:00:00Z")
    monkeypatch.setattr(localize_module, "ensure_snapshot", lambda graph, at: "head-sha")
    monkeypatch.setattr(localize_module, "retrieve", lambda *args, **kwargs: [])
    monkeypatch.setattr(localize_module, "rank", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.repositories.repository_for_graph", lambda name: {"repository_id": "repo-id", "indexed_ref": "head-sha"})
    monkeypatch.setattr("backend.agent.investigation.search_code", lambda *args, **kwargs: {"results": [{"symbol": symbol, "score": 2, "source_url": "https://github.com/owner/repo/blob/head-sha/pkg.py#L3-L5", "evidence_id": "ev1"}]})
    result = localize_module.localize(Graph(), {"title": "retry fails", "created_at": "2019-01-01T00:00:00Z"})
    assert result["as_of"] == "2026-01-01T00:00:00Z"
    assert result["candidates"][0]["origin"] == "current_code"
    assert result["candidates"][0]["direct_evidence"]["evidence_id"] == "ev1"
    assert result["candidates"][0]["paths"] == []


def test_explicit_historical_cutoff_does_not_add_present_day_code(monkeypatch):
    class Graph:
        name = "whygraph_repo"

    monkeypatch.setattr(localize_module, "cutoff", lambda value: value)
    monkeypatch.setattr(localize_module, "ensure_snapshot", lambda graph, at: "old-sha")
    monkeypatch.setattr(localize_module, "retrieve", lambda *args, **kwargs: [])
    monkeypatch.setattr(localize_module, "rank", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.repositories.repository_for_graph", lambda name: {"repository_id": "repo-id", "indexed_ref": "old-sha"})
    def historical_search(*args, **kwargs):
        assert kwargs["as_of"] == "2020-01-01T00:00:00Z"
        return {"results": []}
    monkeypatch.setattr("backend.agent.investigation.search_code", historical_search)
    result = localize_module.localize(Graph(), {"title": "retry", "body": ""}, "2020-01-01T00:00:00Z")
    assert result["as_of"] == "2020-01-01T00:00:00Z"
    assert result["candidates"] == []


def test_high_similarity_unrelated_issue_is_not_diagnostic_evidence(monkeypatch):
    class Graph:
        name = 'fixture'
    seen = []
    monkeypatch.setattr(localize_module, 'ensure_snapshot', lambda *args: 'ref')
    monkeypatch.setattr(localize_module, 'retrieve', lambda *args, **kwargs: [
        {'similarity': .99, 'issue': {'id': 'unrelated', 'title': 'TLS certificate negotiation fails', 'body': 'network socket exception'}}])
    monkeypatch.setattr(localize_module, 'rank', lambda graph, neighbors, *args: seen.extend(neighbors) or [])
    monkeypatch.setattr('backend.repositories.repository_for_graph', lambda *args: None)
    result = localize_module.localize(Graph(), {'title': 'Progress bar updates before processing'})
    assert not seen
    assert result['historical_issues'] == []
    assert result['candidates'] == []
