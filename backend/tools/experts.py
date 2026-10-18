from collections import defaultdict
from backend.graph.queries import query
from backend.tools.common import cutoff, resolve
from backend.graph.snapshots import ensure_snapshot


def experts(graph, path_or_symbol, as_of=None):
    at = cutoff(as_of)
    ref = ensure_snapshot(graph, at if as_of else None)
    files = graph.query("MATCH (f:File)-[e:CONTAINS]->(s:Symbol) WHERE f.path=$path AND e.snapshot_ref=$ref RETURN s.id", {"path": path_or_symbol, "ref": ref})
    symbols = [r[0] for r in files] if files else [resolve(graph, path_or_symbol)]
    # Include verified file relocation predecessors as historical expertise.
    for identity in list(symbols):
        symbols.extend(r[0] for r in graph.query("MATCH (s:Symbol {id:$id}), (old:Symbol), (f:File) WHERE old.qualified_name=s.qualified_name AND f.path=s.file_path MATCH (c:Commit)-[m:MODIFIED]->(f) WHERE m.old_path=old.file_path AND m.status STARTS WITH 'R' AND c.timestamp <= $at RETURN DISTINCT old.id", {"id": identity, "at": at}))
    ranked = defaultdict(lambda: {"direct_changes": 0, "fix_count": 0, "review_count": 0, "sources": []})
    params = {"symbols": symbols, "as_of": at}
    for login, count, latest in graph.query(query("experts"), params):
        ranked[login].update(direct_changes=count, latest=latest)
    author_sources = graph.query("MATCH (person:Person)-[:AUTHORED]->(c:Commit)-[:MODIFIED_SYMBOL]->(s:Symbol) WHERE s.id IN $symbols AND c.timestamp <= $as_of AND person.login <> '' RETURN DISTINCT person.login,c.url", params)
    for login, url in author_sources:
        ranked[login]["sources"].append(url)
    fixes = graph.query("MATCH (person:Person)-[:AUTHORED]->(c:Commit)-[:MODIFIED_SYMBOL]->(s:Symbol), (p:PullRequest)-[:CONTAINS_COMMIT]->(c), (p)-[:CLOSES]->(i:Issue) WHERE s.id IN $symbols AND c.timestamp <= $as_of AND p.merged_at <= $as_of AND i.created_at <= $as_of AND person.login <> '' RETURN person.login,count(DISTINCT i),collect(DISTINCT p.url)", params)
    for login, count, urls in fixes:
        ranked[login]["fix_count"] = count
        ranked[login]["sources"].extend(urls)
    reviews = graph.query("MATCH (person:Person)-[review:REVIEWED]->(p:PullRequest)-[:CONTAINS_COMMIT]->(c:Commit)-[:MODIFIED_SYMBOL]->(s:Symbol) WHERE s.id IN $symbols AND c.timestamp <= $as_of AND p.merged_at <= $as_of AND review.timestamp <= $as_of RETURN person.login,count(DISTINCT p),collect(DISTINCT review.source_url)", params)
    for login, count, urls in reviews:
        ranked[login]["review_count"] = count
        ranked[login]["sources"].extend(urls)
    output = []
    from backend.tools.localize import recency
    for login, evidence in ranked.items():
        evidence["sources"] = sorted(set(evidence["sources"]))
        evidence["recency"] = recency(evidence["latest"], at) if evidence.get("latest") else 0
        output.append({"login": login, "score": evidence["direct_changes"]*2 + evidence["fix_count"] + evidence["review_count"]*.75 + evidence["recency"], **evidence})
    return {"as_of": at, "experts": sorted(output, key=lambda e: (-e["score"], e["login"]))[:5], "formula": "2*direct_changes + fix_count + .75*review_count + recency"}
