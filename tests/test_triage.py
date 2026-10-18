from types import SimpleNamespace
import pytest
import importlib
import httpx

module = importlib.import_module("backend.tools.triage")


def test_preview_never_posts(monkeypatch):
    result = {"localization": {"candidates": [], "confidence": "low", "as_of": "2020-01-01T00:00:00Z", "snapshot_ref": "abc"}, "findings": [], "trace": ["graph evidence"]}
    monkeypatch.setattr(module, "analyze", lambda *args, **kwargs: result)
    monkeypatch.setattr(module, "post_comment", lambda *args: pytest.fail("preview must not post"))
    assert module.triage(None, {"title": "test"})["action"]["posted"] is False


def test_upstream_posting_disabled(monkeypatch):
    monkeypatch.setattr(module, "settings", SimpleNamespace(repo="o/r", triage_fork="o/r"))
    with pytest.raises(ValueError, match="upstream"):
        module.post_comment({"number": 1}, "body")


@pytest.mark.parametrize("changed", [False, True])
def test_verified_fork_action_and_stale_issue_guard(monkeypatch, changed):
    posted = []
    def transport(request):
        path = request.url.path
        if request.method == "POST":
            posted.append(request)
            return httpx.Response(201, json={"html_url": "https://github.com/alice/click/issues/1#issuecomment-123"})
        data = {"/repos/alice/click": {"fork": True, "parent": {"full_name": "pallets/click"}, "owner": {"login": "alice"}}, "/user": {"login": "alice"}, "/repos/alice/click/issues/1": {"title": "Changed title" if changed else "Issue title", "body": "Issue body"}, "/repos/alice/click/issues/1/comments": []}[path]
        return httpx.Response(200, json=data)
    class FakeGitHub:
        def __init__(self, repo):
            self.client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(transport))
        def get(self, route, refresh=False):
            return self.client.get(route).json()
    monkeypatch.setattr(module, "settings", SimpleNamespace(repo="pallets/click", triage_fork="alice/click", github_token="test-placeholder"))
    monkeypatch.setattr(module, "GitHub", FakeGitHub)
    issue = {"number": 1, "title": "Issue title", "body": "Issue body"}
    if changed:
        with pytest.raises(ValueError, match="changed since preview"):
            module.post_comment(issue, "Previewed recommendation <!-- whygraph:test -->")
        assert not posted
    else:
        result = module.post_comment(issue, "Previewed recommendation <!-- whygraph:test -->")
        assert result["url"].endswith("issuecomment-123")
        assert len(posted) == 1 and b"Previewed recommendation" in posted[0].content


@pytest.fixture
def preview_flow(monkeypatch):
    """Exercise preview -> HTTP guard -> comment transport without external writes."""
    import json
    from copy import deepcopy
    issue = {"id": 123, "number": 1, "title": "Reviewed title", "body": "Reviewed body", "state": "open", "html_url": "https://github.com/alice/click/issues/1", "created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-01-01T00:00:00Z"}
    comments, posted, analyzed, refreshes = [], [], [], []
    def transport(request):
        path = request.url.path
        if request.method == "POST":
            body = json.loads(request.content)["body"]
            posted.append(body)
            comment = {"body": body, "html_url": "https://github.com/alice/click/issues/1#issuecomment-123"}
            comments.append(comment)
            return httpx.Response(201, json=comment)
        data = {"/repos/alice/click": {"fork": True, "parent": {"full_name": "pallets/click"}, "owner": {"login": "alice"}}, "/user": {"login": "alice"}, "/repos/alice/click/issues/1": issue, "/repos/alice/click/issues/1/comments": comments}[path]
        return httpx.Response(200, json=data)
    class FakeGitHub:
        def __init__(self, repo):
            self.client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(transport))
        def get(self, route, refresh=False):
            return self.client.get(route).json()
        def issue(self, number, refresh=False):
            refreshes.append(refresh)
            return self.get(f"/repos/alice/click/issues/{number}", refresh)
    class PreviewGraph:
        def __init__(self): self.previews = {}
        def nodes(self, label, rows):
            assert label == "TriagePreview"
            self.previews.update({row["id"]: deepcopy(row) for row in rows})
        def query(self, query, params):
            if "DELETE p" in query: return []
            row = self.previews.get(params["id"])
            return [[SimpleNamespace(properties=row)]] if row else []
    def analyze(graph, value, as_of=None):
        analyzed.append(deepcopy(value))
        return {"localization": {"candidates": [], "confidence": "low", "as_of": "2020-01-01T00:00:00Z", "snapshot_ref": "abc"}, "findings": [], "trace": ["original analysis"]}
    monkeypatch.setattr(module, "settings", SimpleNamespace(repo="pallets/click", triage_fork="alice/click", github_token="test-placeholder"))
    monkeypatch.setattr(module, "GitHub", FakeGitHub)
    monkeypatch.setattr(module, "analyze", analyze)
    return SimpleNamespace(graph=PreviewGraph(), issue=issue, posted=posted, analyzed=analyzed, refreshes=refreshes)


def test_post_uses_saved_markdown_without_new_analysis_and_is_idempotent(preview_flow):
    flow = preview_flow
    preview = module.triage(flow.graph, 1)
    assert flow.refreshes == [True]
    assert not flow.posted
    result = module.triage(flow.graph, 1, post=True, preview_id=preview["preview_id"])
    repeated = module.triage(flow.graph, 1, post=True, preview_id=preview["preview_id"])
    assert flow.posted == [preview["markdown"]]
    assert result["markdown"] == repeated["markdown"] == preview["markdown"]
    assert len(flow.analyzed) == 1
    assert repeated["action"]["already_posted"] is True


@pytest.mark.parametrize("field", ["title", "body"])
def test_full_flow_rejects_issue_changed_after_preview(preview_flow, field):
    flow = preview_flow
    preview = module.triage(flow.graph, 1)
    flow.issue[field] += " edited after preview"
    with pytest.raises(ValueError, match="changed since preview"):
        module.triage(flow.graph, 1, post=True, preview_id=preview["preview_id"])
    assert not flow.posted
    assert len(flow.analyzed) == 1
    # A fresh preview must actually fetch the changed issue.
    module.triage(flow.graph, 1)
    assert flow.analyzed[-1][field] == flow.issue[field]
    assert flow.refreshes == [True, True]


@pytest.mark.parametrize("kind", ["missing", "unknown", "expired", "wrong_issue", "wrong_fork", "wrong_repo", "wrong_cutoff"])
def test_post_requires_matching_unexpired_preview(preview_flow, kind):
    flow = preview_flow
    preview = module.triage(flow.graph, 1)
    token = preview["preview_id"]
    issue_number, as_of = 1, None
    if kind == "missing": token = None
    elif kind == "unknown": token = "unknown"
    elif kind == "expired": flow.graph.previews[token]["expires_at"] = "2000-01-01T00:00:00Z"
    elif kind == "wrong_issue": issue_number = 2
    elif kind == "wrong_fork": flow.graph.previews[token]["issue_repo"] = "bob/click"
    elif kind == "wrong_repo": flow.graph.previews[token]["repo"] = "other/repo"
    elif kind == "wrong_cutoff": as_of = "2021-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        module.triage(flow.graph, issue_number, post=True, preview_id=token, as_of=as_of)
    assert not flow.posted
    assert len(flow.analyzed) == 1


def test_http_preview_to_post_preserves_reviewed_response(preview_flow, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.api import routes
    flow = preview_flow
    monkeypatch.setattr(routes, "graph", lambda: flow.graph)
    client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000))
    preview_response = client.post("/api/query", json={"tool": "triage", "issue_number": 1})
    assert preview_response.status_code == 200
    preview = preview_response.json()
    response = client.post("/api/query", json={"tool": "triage", "issue_number": 1, "post": True, "preview_id": preview["preview_id"]})
    assert response.status_code == 200
    assert response.json()["markdown"] == preview["markdown"]
    assert flow.posted == [preview["markdown"]]
    assert len(flow.analyzed) == 1


def test_http_rejects_stale_issue_and_refreshes_preview(preview_flow, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.api import routes
    flow = preview_flow
    monkeypatch.setattr(routes, "graph", lambda: flow.graph)
    client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000))
    preview = client.post("/api/query", json={"tool": "triage", "issue_number": 1}).json()
    flow.issue["body"] = "Changed after review"
    response = client.post("/api/query", json={"tool": "triage", "issue_number": 1, "post": True, "preview_id": preview["preview_id"]})
    assert response.status_code == 422
    assert "changed since preview" in response.json()["detail"]
    assert not flow.posted
    refreshed = client.post("/api/query", json={"tool": "triage", "issue_number": 1})
    assert refreshed.status_code == 200
    assert refreshed.json()["preview_id"] != preview["preview_id"]
    assert flow.analyzed[-1]["body"] == "Changed after review"
