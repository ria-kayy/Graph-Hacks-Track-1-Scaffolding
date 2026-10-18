"""Reconstruct actual source at the cutoff; edges are tagged with the Git ref."""
import json
from backend.config import ROOT, settings
from backend.graph.client import edge
from backend.ingestion.code_parser import parse_sources, clear_snapshot, PARSER_VERSION
from backend.ingestion.git_history import git, sources_at
from backend.tools.common import snapshot


def ensure_snapshot(graph, as_of=None):
    if as_of is None:
        return snapshot(graph)
    from backend.repositories import repository_for_graph
    record = repository_for_graph(getattr(graph, "name", ""))
    checkout = ROOT / ".data/repo"
    repo_identity = settings.repo
    if record:
        checkout = record["checkout"]
        repo_identity = record["identity"]
    ref = git(checkout, "rev-list", "-1", "--before=" + as_of, snapshot(graph)).strip()
    if not ref:
        raise ValueError("No source revision existed before as_of")
    if graph.query("MATCH (f:File)-[e:CONTAINS]->(s:Symbol) WHERE e.snapshot_ref=$ref AND e.parser_version=$version RETURN s.id LIMIT 1", {"ref": ref, "version": PARSER_VERSION}):
        return ref
    parsed = parse_sources(repo_identity, sources_at(checkout, ref), ref)
    clear_snapshot(graph, ref)
    graph.nodes("File", [{"id": f["id"], "path": f["path"], "language": "python"} for f in parsed.files])
    graph.edges("Repository", "HAS_FILE", "File", [edge(repo_identity, f["id"], ref, snapshot_ref=ref) for f in parsed.files])
    graph.nodes("Symbol", [{k: s[k] for k in ("id", "qualified_name", "name", "kind", "file_path")} for s in parsed.symbols])
    graph.edges("File", "CONTAINS", "Symbol", parsed.contains)
    graph.edges("Symbol", "CALLS", "Symbol", parsed.calls)
    graph.edges("File", "IMPORTS", "File", parsed.imports)
    return ref


def symbol_metadata(graph, identity, ref):
    rows = graph.query("MATCH (f:File)-[e:CONTAINS]->(s:Symbol {id:$id}) WHERE e.snapshot_ref=$ref RETURN s,e.metadata_json", {"id": identity, "ref": ref})
    if not rows:
        return None
    from backend.graph.client import properties
    return json.loads(rows[0][1]) if rows[0][1] else properties(rows[0][0])


def relocated_symbol(graph, identity, ref, at):
    rows = graph.query("MATCH (old:Symbol {id:$id}), (f:File)-[e:CONTAINS]->(s:Symbol) WHERE s.qualified_name=old.qualified_name AND e.snapshot_ref=$ref MATCH (c:Commit)-[move:MODIFIED]->(f) WHERE move.old_path=old.file_path AND move.status STARTS WITH 'R' AND c.timestamp <= $at RETURN s.id,c.url", {"id": identity, "ref": ref, "at": at})
    unique = {row[0] for row in rows}
    return (rows[0][0], rows[0][1]) if len(unique) == 1 else (None, None)
