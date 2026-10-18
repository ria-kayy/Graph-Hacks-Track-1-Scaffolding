from backend.graph.client import properties
from backend.graph.queries import query
from backend.tools.common import cutoff, resolve
from backend.graph.snapshots import ensure_snapshot, symbol_metadata


def history(graph, symbol, as_of=None):
    identity = resolve(graph, symbol)
    at = cutoff(as_of)
    meta = properties(graph.query("MATCH (s:Symbol {id:$id}) RETURN s", {"id": identity})[0][0])
    if as_of:
        ref = ensure_snapshot(graph, at)
        historical = symbol_metadata(graph, identity, ref)
        if not historical:
            raise ValueError("Symbol did not exist in the source snapshot at as_of")
        meta = historical
    identities = [identity]
    identities.extend(row[0] for row in graph.query("MATCH (s:Symbol {id:$id}), (old:Symbol), (f:File) WHERE old.qualified_name=s.qualified_name AND f.path=s.file_path MATCH (c:Commit)-[m:MODIFIED]->(f) WHERE m.old_path=old.file_path AND m.status STARTS WITH 'R' AND c.timestamp <= $at RETURN DISTINCT old.id", {"id": identity, "at": at}))
    records = []
    for commit, pr, issue, changed_symbol in graph.query(query("history"), {"symbols": identities, "as_of": at}):
        p, i = properties(pr), properties(issue)
        for entity in (p, i):
            if entity and entity.get("updated_at", at) > at:
                for key in ("title", "body", "state", "comments_json"):
                    entity.pop(key, None)
        records.append({"commit": properties(commit), "pr": p, "issue": i, "modified_symbol": {k: changed_symbol.properties[k] for k in ("id", "qualified_name", "file_path")}})
    claims = [properties(row[0]) for row in graph.query(query("temporal"), {"symbol": identity, "as_of": at})]
    # A rationale attached to a shared PR does not necessarily explain this symbol.
    # Only explicit symbol EXPLAINS edges from the temporal query are eligible.
    claims = list({c["id"]: c for c in claims}.values())
    from backend.agent.evidence import rationale_evidence
    from backend.repositories import repository_for_graph
    record = repository_for_graph(getattr(graph, "name", ""))
    evidence = rationale_evidence(graph, claims, record["repository_id"] if record else graph.name, at)
    valid_claims = {item["evidence_id"] for item in evidence}
    claims = [claim for claim in claims if claim["id"] in valid_claims]
    sources = sorted({entity["url"] for r in records for entity in r.values() if entity and entity.get("url")} | {c["source_url"] for c in claims if c.get("source_url")})
    return {"symbol": meta, "as_of": at, "timeline": records, "claims": claims, "evidence": evidence, "sources": sources, "note": "No verified rationale was found." if not claims else "Rationale is backed by exact source spans."}
