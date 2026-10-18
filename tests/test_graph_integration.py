"""Real FalkorDB tests. Run WHYGRAPH_INTEGRATION=1 pytest -m integration."""
import os
import uuid
import pytest
from backend.graph.client import Graph, edge
from backend.ingestion.code_parser import parse_sources, persist
from backend.tools.localize import rank, historical_fixes
from backend.tools.impact import impact
from backend.tools.history import history
from backend.graph.vectors import retrieve

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv("WHYGRAPH_INTEGRATION") != "1", reason="requires a real FalkorDB runtime")]


@pytest.fixture
def graph():
    g = Graph("whygraph_test_" + uuid.uuid4().hex)
    g.initialize()
    yield g
    g.graph.delete()


def tiny_graph(g):
    repo, ref = "test/repo", "test-ref"
    g.nodes("Repository", [{"id": repo, "indexed_ref": ref}])
    parsed = parse_sources(repo, {"a.py": "def responsible():\n    return 1\ndef caller():\n    return responsible()\ndef future():\n    return 2\n"}, ref)
    persist(g, parsed, repo, ref)
    by_name = {s["name"]: s["id"] for s in parsed.symbols}
    for suffix, year, name in (("old", "2018", "responsible"), ("future", "2021", "future")):
        at = year + "-01-01T00:00:00Z"
        g.nodes("Issue", [{"id": suffix, "number": 1 if suffix == "old" else 2, "title": suffix, "body": suffix, "created_at": at, "updated_at": at, "url": "https://example.org/issue/" + suffix}])
        g.nodes("PullRequest", [{"id": "pr-"+suffix, "number": 1, "created_at": at, "merged_at": at, "url": "https://example.org/pr/"+suffix}])
        g.nodes("Commit", [{"id": "c-"+suffix, "sha": "c-"+suffix, "timestamp": at, "url": "https://example.org/commit/"+suffix}])
        props = {"timestamp": at, "source_url": "https://example.org/evidence", "source_type": "test", "confidence": 1.0}
        g.edges("PullRequest", "CLOSES", "Issue", [edge("pr-"+suffix, suffix, suffix, **props)])
        g.edges("PullRequest", "CONTAINS_COMMIT", "Commit", [edge("pr-"+suffix, "c-"+suffix, suffix, **props)])
        g.edges("Commit", "MODIFIED_SYMBOL", "Symbol", [edge("c-"+suffix, by_name[name], suffix, **props)])
    neighbors = [{"issue": {"id": suffix, "number": index+1, "title": suffix, "url": "https://example.org/issue/"+suffix}, "similarity": similarity} for index, (suffix, similarity) in enumerate((("old", .8), ("future", .99)))]
    return by_name, neighbors, ref


def test_localization_ranking_and_no_future_paths(graph):
    symbols, neighbors, ref = tiny_graph(graph)
    at = "2019-01-01T00:00:00Z"
    rows = historical_fixes(graph, neighbors, at)
    assert all(row[0] == "old" for row in rows)
    candidates = rank(graph, neighbors, at, ref)
    assert candidates[0]["symbol"]["id"] == symbols["responsible"]
    assert all(p["commit"]["timestamp"] <= at for c in candidates for p in c["paths"])
    assert candidates[0]["components"]["historical_fix_frequency"] == 1


def test_impact_and_history_sources(graph):
    symbols, _, _ = tiny_graph(graph)
    result = impact(graph, symbols["responsible"])
    assert result["direct_callers"][0]["path"] == ["a.caller", "a.responsible"]
    result = history(graph, symbols["responsible"])
    assert result["timeline"][0]["pr"]["id"] == "pr-old"
    assert len(result["sources"]) == 3


def test_vector_direction_and_future_neighbor_crowding(graph, monkeypatch):
    graph.query("CREATE VECTOR INDEX FOR (n:Issue) ON (n.embedding) OPTIONS {dimension:2,similarityFunction:'cosine'}")
    graph.query("CREATE (:Issue {id:'old',number:1,title:'old',body:'',created_at:'2018-01-01T00:00:00Z',updated_at:'2018-01-01T00:00:00Z',embedding:vecf32([1,0])})")
    for index in range(4):
        graph.query("CREATE (:Issue {id:$id,number:2,title:'future',body:'',created_at:'2021-01-01T00:00:00Z',updated_at:'2021-01-01T00:00:00Z',embedding:vecf32([1,0])})", {"id": f"future{index}"})
    monkeypatch.setattr("backend.graph.vectors.embed", lambda texts: [[1.0, 0.0]])
    result = retrieve(graph, "query", "2019-01-01T00:00:00Z", k=1)
    assert result[0]["issue"]["id"] == "old"
    assert abs(result[0]["similarity"]-1) < 1e-5


def test_claim_valid_to_boundary(graph):
    symbols, _, _ = tiny_graph(graph)
    graph.nodes("Claim", [{"id": "old-claim", "text": "Old behavior", "created_at": "2018-01-01T00:00:00Z", "valid_from": "2018-01-01T00:00:00Z", "valid_to": "2020-01-01T00:00:00Z"}])
    graph.edges("Claim", "EXPLAINS", "Symbol", [edge("old-claim", symbols["responsible"], "old-claim")])
    from backend.graph.queries import query
    assert graph.query(query("temporal"), {"symbol": symbols["responsible"], "as_of": "2019-01-01T00:00:00Z"})
    assert not graph.query(query("temporal"), {"symbol": symbols["responsible"], "as_of": "2020-01-01T00:00:00Z"})


def test_numbered_preview_survives_new_graph_client_and_posts_exact_comment(graph, monkeypatch):
    import importlib
    from types import SimpleNamespace
    module = importlib.import_module("backend.tools.triage")
    monkeypatch.setattr(module, "settings", SimpleNamespace(repo="pallets/click", triage_fork="alice/click"))
    original = {"localization": {"candidates": [], "confidence": "low", "as_of": "2020-01-01T00:00:00Z", "snapshot_ref": "abc"}, "findings": [], "trace": ["saved analysis"], "markdown": "Exact reviewed comment", "action": {"posted": False}}
    issue = {"number": 1, "title": "Original issue", "body": "Original body"}
    module.save_preview(graph, issue, original)
    # A new connection simulates another worker/restarted backend, not process memory.
    reopened = Graph(graph.name)
    monkeypatch.setattr(module, "analyze", lambda *args, **kwargs: pytest.fail("must not reanalyze"))
    received = []
    monkeypatch.setattr(module, "post_comment", lambda value, body: received.append((value, body)) or {"url": "https://example.org/comment"})
    result = module.triage(reopened, 1, post=True, preview_id=original["preview_id"])
    assert received == [(issue, original["markdown"])]
    assert result["trace"] == original["trace"]
    assert result["markdown"] == original["markdown"]
