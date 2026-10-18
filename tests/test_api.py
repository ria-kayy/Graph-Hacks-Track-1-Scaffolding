from fastapi.testclient import TestClient
from backend.main import app
from backend.api import routes


def test_invalid_tool_and_action_flag_are_rejected(monkeypatch):
    monkeypatch.setattr(routes, "graph", lambda: None)
    client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000))
    assert client.post("/api/query", json={"tool": "unknown"}).status_code == 422
    assert client.post("/api/query", json={"tool": "history", "symbol": "x", "post": True}).status_code == 422
    assert client.post("/api/query", json={"tool": "triage", "post": True}).status_code == 422


def test_date_error_is_friendly_and_does_not_need_database(monkeypatch):
    def unavailable():
        raise AssertionError("date must be validated before connecting")
    monkeypatch.setattr(routes, "graph", unavailable)
    response = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000)).post("/api/query", json={"tool": "history", "symbol": "x", "as_of": "abc"})
    assert response.status_code == 422
    assert "ISO timestamp" in response.json()["detail"]
    assert "2026-10-04T00:00:00Z" in response.json()["detail"]


def test_post_without_preview_is_rejected_before_database_access(monkeypatch):
    monkeypatch.setattr(routes, "graph", lambda: (_ for _ in ()).throw(AssertionError("no database access")))
    response = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000)).post("/api/query", json={"tool": "triage", "issue_number": 1, "post": True})
    assert response.status_code == 422
    assert "preview" in response.json()["detail"]


def test_custom_repository_triage_cannot_reach_configured_default_fork(monkeypatch):
    monkeypatch.setattr(routes, "graph", lambda: (_ for _ in ()).throw(AssertionError("triage must be rejected before graph access")))
    response = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000)).post("/api/query", json={"tool": "triage", "repo_id": "repo-b", "title": "failure"})
    assert response.status_code == 422
    assert "default repository" in response.json()["detail"]
