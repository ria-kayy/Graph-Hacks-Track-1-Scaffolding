import json
from functools import lru_cache
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.config import ROOT, settings
from backend.graph.client import Graph, properties
from backend.tools.history import history
from backend.tools.impact import impact
from backend.tools.experts import experts
from backend.tools.similar import similar_issues
from backend.tools.localize import localize
from backend.tools.triage import triage
from backend.tools.common import cutoff
from backend.repositories import repositories, register, get_repository, start_ingestion, get_job
from backend.agent.investigation import investigate

router = APIRouter(prefix="/api")


@lru_cache(maxsize=1)
def graph():
    return Graph()


@lru_cache(maxsize=32)
def repository_graph(name: str):
    return Graph(name)


def get_graph(repo_id: str | None = None):
    if not repo_id:
        return graph()
    record = get_repository(repo_id)
    if record["status"] in ("queued", "indexing", "failed"):
        raise ValueError("Repository is not ready; inspect ingestion status")
    return repository_graph(record["graph_name"])


class RepositoryRequest(BaseModel):
    repository: str = Field(min_length=1, max_length=500)


class ChatRequest(BaseModel):
    repo_id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=10000)
    conversation_id: str | None = Field(default=None, max_length=64)
    as_of: str | None = None
    context: str = Field(default="", max_length=3000)


class Query(BaseModel):
    tool: Literal["history", "impact", "experts", "similar_issues", "localize", "triage"]
    symbol: str = ""
    text: str = Field(default="", max_length=20000)
    issue_number: int | None = Field(default=None, gt=0)
    title: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    as_of: str | None = None
    post: bool = False
    preview_id: str | None = Field(default=None, min_length=1, max_length=64)
    repo_id: str | None = None


@router.post("/repositories")
def add_repository(request: RepositoryRequest):
    try:
        record, created = register(request.repository)
        job = start_ingestion(record["repository_id"]) if created or record["status"] in ("queued", "indexing", "failed") else None
        return {"repository": get_repository(record["repository_id"]), "job": job}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/repositories")
def list_repositories():
    return {"repositories": repositories()}


@router.get("/repositories/{repo_id}")
def repository_status(repo_id: str):
    try:
        return get_repository(repo_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/repositories/{repo_id}/refresh")
def refresh_repository(repo_id: str):
    try:
        return start_ingestion(repo_id, refresh=True)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/ingestion-jobs/{job_id}")
def ingestion_job(job_id: str):
    try:
        return get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/chat")
def chat(request: ChatRequest):
    try:
        return investigate(request.repo_id, request.query, request.conversation_id, request.as_of, request.context)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/status")
def status():
    g = graph()
    repo = g.query("MATCH (r:Repository) RETURN r")
    repository = properties(repo[0][0]) if repo else None
    counts = {label: g.query(f"MATCH (n:{label}) RETURN count(n)")[0][0] for label in ("Symbol", "Commit", "PullRequest", "Issue", "Claim")}
    symbols = g.query("MATCH (f:File)-[e:CONTAINS]->(s:Symbol) WHERE e.snapshot_ref=$ref RETURN s.id,s.qualified_name ORDER BY s.qualified_name", {"ref": repository["indexed_ref"] if repository else ""})
    graph_counts = dict(counts)
    counts["Symbol"] = len(symbols)
    return {"repository": repository, "counts": counts, "graph_counts": graph_counts, "current_symbols": len(symbols), "symbols": [{"id": i, "name": n} for i, n in symbols], "posting_configured": bool(settings.triage_fork and settings.github_token), "fork": settings.triage_fork or None, "persistence": "FalkorDB", "runtime": settings.mode}


@router.get("/evaluation")
def evaluation():
    path = ROOT / "evaluation/results.json"
    if not path.exists():
        raise HTTPException(404, "No measured results. Run python -m evaluation.run")
    return json.loads(path.read_text())


@router.post("/query")
def execute(request: Query):
    try:
        if request.as_of:
            cutoff(request.as_of)
        if request.post and request.tool != "triage":
            raise ValueError("post is only valid for triage")
        if request.tool == "triage" and request.repo_id not in (None, "default"):
            raise ValueError("Triage previews and GitHub actions are currently limited to the configured default repository")
        if request.preview_id and request.tool != "triage":
            raise ValueError("preview_id is only valid for triage")
        if request.post and (request.issue_number is None or not request.preview_id):
            raise ValueError("Select an existing fork issue and generate a preview before posting")
        g = get_graph(request.repo_id)
        if request.tool in ("history", "impact", "experts"):
            if not request.symbol:
                raise ValueError("A symbol or file path is required")
            return {"history": history, "impact": impact, "experts": experts}[request.tool](g, request.symbol, request.as_of)
        if request.tool == "similar_issues":
            if not request.text:
                raise ValueError("Issue text is required")
            return similar_issues(g, request.text, request.as_of)
        issue = {"title": request.title, "body": request.body}
        if request.tool == "triage":
            if request.post and request.issue_number is None:
                raise ValueError("Select an existing fork issue before posting")
            return triage(g, request.issue_number if request.issue_number else issue, request.post, request.as_of, request.preview_id)
        if not request.title and not request.body:
            raise ValueError("Issue title or body is required")
        return localize(g, issue, request.as_of)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class ToolRequest(BaseModel):
    repo_id: str = Field(min_length=1, max_length=64)
    tool: Literal["search_code", "search_commits", "read_source", "get_symbol_context", "trace_callers", "trace_callees", "history", "impact", "experts", "similar_issues", "localize"]
    arguments: dict = Field(default_factory=dict)
    as_of: str | None = None


@router.post("/tools")
def investigation_tool(request: ToolRequest):
    from backend.agent.toolbox import dispatch
    try:
        if request.as_of:
            cutoff(request.as_of)
        get_repository(request.repo_id)
        return dispatch(request.repo_id, request.as_of, request.tool, request.arguments)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, "Invalid investigation tool arguments or unavailable source") from exc


@router.get("/health")
def health():
    graph().query("RETURN 1")
    return {"ok": True, "store": "FalkorDB"}
