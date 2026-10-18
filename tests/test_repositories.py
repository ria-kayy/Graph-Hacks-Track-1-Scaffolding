import pytest

from backend import repositories
from backend.agent import investigation
from backend.api import routes
from fastapi.testclient import TestClient
from backend.main import app


@pytest.mark.parametrize("value, expected", [
    ("https://github.com/Pallets/Click.git", "pallets/click"),
    ("pallets/click", "pallets/click"),
])
def test_canonical_github_identity(value, expected):
    assert repositories.canonical_repo(value) == expected


@pytest.mark.parametrize("value", [
    "C:\\Users\\me\\repo", "https://gitlab.com/a/b", "https://github.com/a/b?x=1",
    "../repo/name", "https://user:pass@github.com/a/b", "owner/..", "bad_owner/repo", "-owner/repo", "owner./repo",
])
def test_rejects_unsafe_or_unsupported_repository(value):
    with pytest.raises(ValueError):
        repositories.canonical_repo(value)


def test_repository_namespaces_are_stable_and_isolated():
    a, b = repositories.repository_id("pallets/click"), repositories.repository_id("psf/requests")
    assert a != b
    assert "whygraph_" + a != "whygraph_" + b
    assert repositories.repository_id("pallets/click") == a


def test_chat_api_is_repository_explicit_and_returns_structured_result(monkeypatch):
    monkeypatch.setattr(routes, "investigate", lambda repo_id, query, conversation_id, as_of, context: {
        "answer": "Found source", "repository_id": repo_id, "conversation_id": "c1", "evidence": [], "tools_used": []
    })
    client = TestClient(app)
    missing = client.post("/api/chat", json={"query": "where is retry"})
    assert missing.status_code == 422
    response = client.post("/api/chat", json={"repo_id": "repo-a", "query": "where is retry"})
    assert response.status_code == 200
    assert response.json()["repository_id"] == "repo-a"
    assert response.json()["conversation_id"] == "c1"


def test_conversation_cannot_cross_repository(monkeypatch):
    investigation._conversations.clear()
    first = "conversation-test"
    investigation._conversations[first] = {"repository_id": "repo-a", "query": "retry", "symbols": []}
    with pytest.raises(ValueError, match="different repository"):
        investigation.investigate("repo-b", "why did it change?", first)
