"""Repository identity, isolated storage and bounded local ingestion jobs."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from backend.config import ROOT, settings

DATA = ROOT / ".data"
REGISTRY = DATA / "repositories.json"
_lock = threading.RLock()
_slots = threading.BoundedSemaphore(8)
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whygraph-ingest")
_jobs: dict[str, dict] = {}


def canonical_repo(value: str) -> str:
    value = value.strip()
    if value.startswith(("https://", "http://", "git@")):
        parsed = urlparse(value.replace("git@github.com:", "https://github.com/"))
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
            raise ValueError("Only canonical public GitHub repository URLs are supported")
        value = parsed.path.strip("/")
    value = value.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", value) or value in (".", "..") or any(p in (".", "..") for p in value.split("/")):
        raise ValueError("Enter a GitHub URL or owner/repository identifier")
    owner, name = value.split("/")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner):
        raise ValueError("Enter a valid GitHub owner name")
    return value.lower()


def repository_id(repo: str) -> str:
    return hashlib.sha256(repo.encode()).hexdigest()[:24]


@dataclass(frozen=True)
class RepositoryContext:
    repository_id: str
    identity: str
    checkout: Path
    graph_name: str
    selected_revision: str | None = None
    github_token: str = ""
    state: str = "registered"


def _read() -> dict:
    if not REGISTRY.exists():
        return {}
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    # Jobs left active by a previous process are recoverable, never silently ready.
    for record in data.values():
        job = record.get("job")
        if job and job["status"] in ("queued", "running") and job["job_id"] not in _jobs:
            record["status"] = "failed"
            record["error"] = "Ingestion interrupted by backend restart; refresh to retry"
            job.update(status="failed", error=record["error"])
    return data


def _write(data):
    DATA.mkdir(parents=True, exist_ok=True)
    temporary = REGISTRY.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(REGISTRY)


def repositories() -> list[dict]:
    return [{"repository_id": "default", "identity": settings.repo, "url": f"https://github.com/{settings.repo}", "checkout": str(DATA / "repo"), "graph_name": settings.graph, "indexed_ref": None, "status": "default", "counts": {}}] + list(_read().values())


def get_repository(repo_id: str) -> dict:
    if repo_id == "default":
        return {"repository_id": "default", "identity": settings.repo, "url": f"https://github.com/{settings.repo}", "checkout": str(DATA / "repo"), "graph_name": settings.graph, "indexed_ref": None, "status": "default", "counts": {}}
    record = _read().get(repo_id)
    if not record:
        raise KeyError("Unknown repository")
    return record


def context(repo_id: str) -> RepositoryContext:
    record = get_repository(repo_id)
    if record["status"] in ("queued", "indexing", "failed"):
        raise ValueError("Repository is not ready; inspect ingestion status and refresh if needed")
    return RepositoryContext(repo_id, record["identity"], Path(record["checkout"]), record["graph_name"], record.get("indexed_ref"), state=record["status"])


def repository_for_graph(graph_name: str) -> dict | None:
    return next((item for item in repositories() if item["graph_name"] == graph_name), None)


def register(value: str) -> tuple[dict, bool]:
    identity = canonical_repo(value)
    rid = repository_id(identity)
    with _lock:
        data = _read()
        if rid in data:
            return data[rid], False
        record = {"repository_id": rid, "identity": identity, "url": f"https://github.com/{identity}", "checkout": str(DATA / "repos" / rid), "graph_name": "whygraph_" + rid, "status": "queued", "indexed_ref": None, "counts": {}, "error": None, "job_id": None}
        data[rid] = record
        _write(data)
    return record, True


def update(repo_id: str, **fields) -> dict:
    with _lock:
        data = _read()
        data[repo_id].update(fields)
        _write(data)
        return data[repo_id]


def start_ingestion(repo_id: str, refresh: bool = False) -> dict:
    import uuid
    if repo_id == "default":
        raise ValueError("Register the default repository URL first to use managed refresh")
    with _lock:
        record = get_repository(repo_id)
        previous = _jobs.get(record.get("job_id"))
        if previous and previous["status"] in ("queued", "running"):
            return dict(previous)
        if not _slots.acquire(blocking=False):
            raise ValueError("Ingestion queue is full; retry after an active job completes")
        for old_id in list(_jobs)[:-128]:
            if _jobs[old_id]["status"] not in ("queued", "running"):
                _jobs.pop(old_id, None)
        job_id = uuid.uuid4().hex
        job = {"job_id": job_id, "repository_id": repo_id, "status": "queued", "stage": "queued", "progress": 0, "error": None}
        _jobs[job_id] = job
        try:
            update(repo_id, status="queued", error=None, job_id=job_id, job=dict(job))
            future = _pool.submit(_ingest, repo_id, job_id, refresh)
            future.add_done_callback(lambda _: _slots.release())
        except Exception:
            _slots.release()
            _jobs.pop(job_id, None)
            raise
        return dict(job)


def get_job(job_id: str) -> dict:
    with _lock:
        if job_id in _jobs:
            return dict(_jobs[job_id])
        for record in _read().values():
            if record.get("job_id") == job_id and record.get("job"):
                return dict(record["job"])
    raise KeyError("Unknown ingestion job")


def _job_update(repo_id, job_id, **fields):
    with _lock:
        _jobs[job_id].update(fields)
        update(repo_id, job=dict(_jobs[job_id]))


def _ingest(repo_id: str, job_id: str, refresh: bool):
    record = get_repository(repo_id)
    checkout = Path(record["checkout"])
    def stage(name, progress):
        _job_update(repo_id, job_id, status="running", stage=name, progress=progress)
        update(repo_id, status="indexing", stage=name)
    try:
        stage("clone_or_fetch", 5)
        checkout.parent.mkdir(parents=True, exist_ok=True)
        if not (checkout / ".git").exists():
            subprocess.run(["git", "clone", "--depth", "500", record["url"] + ".git", str(checkout)], check=True, capture_output=True, text=True, timeout=600)
        else:
            # Verify origin before fetching; never permit a user path or a changed remote.
            origin = subprocess.run(["git", "-C", str(checkout), "remote", "get-url", "origin"], check=True, capture_output=True, text=True, timeout=20).stdout.strip().removesuffix(".git")
            if origin != record["url"]:
                raise ValueError("Stored checkout remote does not match repository identity")
            if refresh:
                subprocess.run(["git", "-C", str(checkout), "fetch", "--depth", "500", "origin"], check=True, capture_output=True, text=True, timeout=600)
                subprocess.run(["git", "-C", str(checkout), "reset", "--hard", "origin/HEAD"], check=True, capture_output=True, text=True, timeout=60)
        from backend.graph.client import Graph
        from backend.ingestion.git_history import git, sources_at, ingest_history
        from backend.ingestion.code_parser import parse_sources, persist
        from backend.ingestion.github import ingest_github
        graph = Graph(record["graph_name"])
        graph.initialize()
        ref = git(checkout, "rev-parse", "HEAD").strip()
        if not git(checkout, "ls-tree", "-r", "--name-only", ref).strip():
            raise ValueError("Repository is empty")
        stage("parse_and_index_code", 20)
        tree = git(checkout, "ls-tree", "-r", "-l", ref).splitlines()
        python_rows = [line for line in tree if line.endswith(".py") and not line.split("\t", 1)[-1].startswith(("tests/", "docs/", "examples/"))]
        if len(python_rows) > 5000:
            raise ValueError("Repository exceeds the 5,000-file Python ingestion limit")
        sizes = []
        for line in python_rows:
            header, _path = line.split("\t", 1)
            fields = header.split()
            size = int(fields[3]) if len(fields) > 3 else 0
            if size > 2_000_000:
                raise ValueError("A Python source file exceeds the 2 MB ingestion limit")
            sizes.append(size)
        if sum(sizes) > 100_000_000:
            raise ValueError("Repository exceeds the 100 MB Python source ingestion limit")
        sources = sources_at(checkout, ref)
        parsed = parse_sources(record["identity"], sources, ref)
        graph.nodes("Repository", [{"id": record["identity"], "url": record["url"]}])
        persist(graph, parsed, record["identity"], ref)
        stage("git_history", 45)
        commits = ingest_history(graph, record["identity"], checkout, ref, max_commits=500)
        graph.nodes("Repository", [{"id": record["identity"], "owner": record["identity"].split("/")[0], "name": record["identity"].split("/")[1], "url": record["url"], "indexed_ref": ref, "indexed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}])
        # Historical ingestion updates shared symbol properties. Restore current
        # metadata after it, while retaining per-snapshot CONTAINS metadata.
        graph.nodes("Symbol", parsed.symbols)
        optional_errors = [f"Python parse failure: {warning['path']}: {warning['error']}" for warning in parsed.warnings]
        stage("github_history", 75)
        try:
            ingest_github(graph, record["identity"], limit=25, checkout=checkout, refresh=refresh, recent=True)
        except Exception as exc:
            optional_errors.append("GitHub issue/PR enrichment: " + str(exc)[:300])
        graph.nodes("Symbol", parsed.symbols)
        stage("rationale", 84)
        try:
            from backend.ingestion.claims import extract_claims
            extract_claims(graph)
        except Exception as exc:
            optional_errors.append("Rationale extraction unavailable: " + str(exc)[:250])
        stage("embeddings", 88)
        try:
            from backend.graph.vectors import index_embeddings
            index_embeddings(graph)
        except Exception as exc:
            optional_errors.append("Embedding generation unavailable: " + str(exc)[:250])
        graph_counts = {label: graph.query(f"MATCH (n:{label}) RETURN count(n)")[0][0] for label in ("Symbol", "Commit", "PullRequest", "Issue")}
        counts = dict(graph_counts)
        counts["Symbol"] = graph.query("MATCH ()-[e:CONTAINS]->(s:Symbol) WHERE e.snapshot_ref=$ref RETURN count(DISTINCT s)", {"ref": ref})[0][0]
        graph.query("MATCH (r:Repository {id:$id}) SET r.ingestion_stage='complete'", {"id": record["identity"]})
        update(repo_id, status="ready_with_warnings" if optional_errors else "ready", indexed_ref=ref, counts=counts, graph_counts=graph_counts, warnings=optional_errors, error=None, stage="complete")
        _job_update(repo_id, job_id, status="completed", stage="complete", progress=100, error=None, warnings=optional_errors)
    except Exception as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        detail = str(detail).strip()[:500]
        _job_update(repo_id, job_id, status="failed", stage=_jobs[job_id].get("stage"), error=detail)
        update(repo_id, status="failed", error=detail)
