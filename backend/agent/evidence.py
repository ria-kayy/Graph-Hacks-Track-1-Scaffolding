"""Canonical citations constructed by trusted retrieval code, never by a model."""
import hashlib
import subprocess
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    model_config = ConfigDict(extra="allow")
    evidence_id: str
    repository_id: str
    evidence_type: Literal["source", "commit", "rationale"]
    source_url: str
    commit_sha: str | None = None
    file_path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    excerpt: str
    symbol_id: str | None = None
    timestamp: str | None = None
    relationship: str
    score: float = 0.0


def read_revision(ctx, revision: str, path: str) -> str:
    """Read a Git blob, including for dirty working trees; never follow symlinks."""
    if not path or PurePosixPath(path).is_absolute() or any(p in ("", ".", "..") for p in path.split("/")) or "\\" in path:
        raise ValueError("Expected an indexed repository-relative file path")
    if not revision or not all(c in "0123456789abcdef" for c in revision) or len(revision) != 40:
        raise ValueError("Source citations require a resolved Git commit SHA")
    result = subprocess.run(["git", "-C", str(ctx.checkout), "show", f"{revision}:{path}"], check=True, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=15)
    if len(result.stdout.encode()) > 2_000_000:
        raise ValueError("Source exceeds the 2 MB read limit")
    return result.stdout


def source_evidence(ctx, revision, path, source, start, end, symbol=None, **signals):
    lines = source.splitlines()
    if start < 1 or end < start or end > len(lines):
        raise ValueError("Source span does not exist in the indexed revision")
    excerpt = "\n".join(f"{n}: {lines[n-1]}" for n in range(start, end + 1))
    identity = hashlib.sha256(f"{ctx.repository_id}:{revision}:{path}:{start}:{end}".encode()).hexdigest()[:24]
    return Evidence(evidence_id=identity, repository_id=ctx.repository_id, evidence_type="source",
                    source_url=f"https://github.com/{ctx.identity}/blob/{revision}/{quote(path, safe='/')}#L{start}-L{end}",
                    file_path=path, commit_sha=revision, start_line=start, end_line=end, excerpt=excerpt,
                    symbol_id=symbol["id"] if symbol else None, relationship="direct source observation",
                    **signals, **({"symbol": symbol} if symbol else {})).model_dump(exclude_none=True)


def validate_evidence(items, ctx, revision, as_of=None):
    """Reject citations outside the active repository, snapshot or source spans."""
    from backend.tools.common import cutoff
    at = cutoff(as_of)
    valid, rejected, blobs = [], [], {}
    for item in items:
        try:
            evidence = Evidence.model_validate(item)
            if evidence.repository_id != ctx.repository_id:
                raise ValueError("Repository mismatch")
            if evidence.timestamp and cutoff(evidence.timestamp) > at:
                raise ValueError("Evidence newer than cutoff")
            if evidence.evidence_type == "source":
                if evidence.commit_sha != revision:
                    raise ValueError("Snapshot mismatch")
                path = evidence.file_path
                if evidence.symbol_id:
                    from backend.graph.client import Graph
                    from backend.graph.snapshots import symbol_metadata
                    symbol = symbol_metadata(Graph(ctx.graph_name), evidence.symbol_id, revision)
                    if not symbol or symbol.get("file_path") != path or symbol.get("start_line") != evidence.start_line or symbol.get("end_line", 0) < evidence.end_line:
                        raise ValueError("Symbol does not match snapshot source span")
                if path not in blobs:
                    blobs[path] = read_revision(ctx, revision, path)
                expected = source_evidence(ctx, revision, path, blobs[path], evidence.start_line, evidence.end_line, item.get("symbol"))
                if any(item.get(k) != expected[k] for k in ("evidence_id", "source_url", "excerpt", "symbol_id") if k in expected):
                    raise ValueError("Source citation does not match retrieved span")
            elif evidence.evidence_type == "commit":
                from backend.graph.client import Graph, properties
                rows = Graph(ctx.graph_name).query("MATCH (c:Commit {id:$sha}) RETURN c", {"sha": evidence.commit_sha})
                commit = properties(rows[0][0]) if rows else None
                if not commit or commit["message"] != evidence.excerpt or commit["url"] != evidence.source_url or commit["timestamp"] != evidence.timestamp:
                    raise ValueError("Commit source mismatch")
                if evidence.source_url != f"https://github.com/{ctx.identity}/commit/{evidence.commit_sha}":
                    raise ValueError("Commit repository mismatch")
            elif evidence.evidence_type == "rationale":
                from backend.graph.client import Graph, properties
                graph = Graph(ctx.graph_name)
                rows = graph.query("MATCH (c:Claim {id:$id}) RETURN c", {"id": evidence.evidence_id})
                claims = [properties(row[0]) for row in rows]
                verified = rationale_evidence(graph, claims, ctx.repository_id, at)
                if not any(v["source_url"] == evidence.source_url and v["excerpt"] == evidence.excerpt for v in verified):
                    raise ValueError("Rationale source mismatch")
            valid.append(item)
        except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
            rejected.append(item.get("evidence_id", "unknown"))
    return valid, rejected


def rationale_evidence(graph, claims, repo_id, at):
    """Validate an attributed quote against its stored original source record."""
    import json
    from backend.graph.client import properties
    from backend.tools.common import cutoff
    output = []
    for claim in claims:
        span, url = claim.get('source_span', ''), claim.get('source_url', '')
        if not span or claim.get('text') != span:
            continue
        rows = graph.query('MATCH (c:Claim {id:$id})-[:SUPPORTED_BY]->(n) RETURN n', {'id': claim['id']})
        for (node,) in rows:
            source = properties(node)
            records = [{'body': source.get('body', ''), 'html_url': source.get('url'), 'updated_at': source.get('updated_at', source.get('created_at'))}]
            records += json.loads(source.get('comments_json', '[]'))
            if any(record.get('html_url') == url and span in (record.get('body') or '') and record.get('updated_at', record.get('submitted_at', record.get('created_at'))) and cutoff(record.get('updated_at', record.get('submitted_at', record.get('created_at')))) <= at for record in records):
                output.append(Evidence(evidence_id=claim['id'], repository_id=repo_id, evidence_type='rationale', source_url=url, excerpt=span, timestamp=claim['source_timestamp'], relationship='explicitly attributed source quote').model_dump(exclude_none=True))
                break
    return output
