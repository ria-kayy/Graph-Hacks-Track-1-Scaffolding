"""Explicit graph traversal and inspectable scoring; no LLM chooses functions."""
import logging
from datetime import datetime
from backend.graph.client import properties
from backend.graph.queries import query
from backend.graph.snapshots import ensure_snapshot, symbol_metadata, relocated_symbol
from backend.graph.vectors import retrieve
from backend.tools.common import cutoff

WEIGHTS = {"semantic_issue_similarity": .40, "historical_fix_frequency": .25, "graph_proximity": .20, "recency": .10, "call_graph_support": .05}


def score(components):
    return sum(WEIGHTS[key] * components[key] for key in WEIGHTS)


def recency(timestamp, at):
    days = max(0, (datetime.fromisoformat(at.replace("Z", "+00:00")) - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()/86400)
    return 1/(1+days/365)


def historical_fixes(graph, issues, at):
    return graph.query(query("localization"), {"issues": [i["issue"]["id"] for i in issues], "as_of": at}) if issues else []


def rank(graph, neighbors, at, ref, expand=True):
    similarities = {item["issue"]["id"]: item["similarity"] for item in neighbors}
    issue_lookup = {item["issue"]["id"]: item["issue"] for item in neighbors}
    candidates = {}

    def add(identity, issue_id, pr, commit, origin, relation=None):
        metadata = symbol_metadata(graph, identity, ref)
        relocation = None
        if not metadata and relation is None:
            current, relocation = relocated_symbol(graph, identity, ref, at)
            if current:
                identity = current
                metadata = symbol_metadata(graph, identity, ref)
        if not metadata or metadata["kind"] == "class":
            return
        candidate = candidates.setdefault(identity, {"symbol": metadata, "paths": [], "fix_issues": set(), "similarity": 0.0, "proximity": 0.0, "recency": 0.0, "call_support": 0.0})
        direct = relation is None
        candidate["similarity"] = max(candidate["similarity"], similarities[issue_id])
        candidate["proximity"] = max(candidate["proximity"], 1.0 if direct else .65 if relation in ("CALLS", "CALLED_BY") else .3)
        candidate["recency"] = max(candidate["recency"], recency(commit["timestamp"], at))
        if direct:
            candidate["fix_issues"].add(issue_id)
        if relation in ("CALLS", "CALLED_BY"):
            candidate["call_support"] = 1.0
        path = {"issue": {k: issue_lookup[issue_id][k] for k in ("id", "number", "title", "url")}, "pr": {k: pr[k] for k in ("id", "number", "url", "merged_at")}, "commit": {k: commit[k] for k in ("sha", "url", "timestamp")}, "modified_symbol": origin, "candidate": identity, "expansion": relation, "relocation_source": relocation, "similarity": similarities[issue_id]}
        if path not in candidate["paths"]:
            candidate["paths"].append(path)

    rows = historical_fixes(graph, neighbors, at)
    for issue_id, p, c, symbol in rows:
        pr, commit, s = properties(p), properties(c), properties(symbol)
        identity = s["id"]
        add(identity, issue_id, pr, commit, identity)
        if expand:
            seed = identity
            if not symbol_metadata(graph, seed, ref):
                seed, _ = relocated_symbol(graph, seed, ref, at)
            if not seed:
                continue
            call_neighbors = graph.query("MATCH (s:Symbol {id:$id})-[e:CALLS]-(n:Symbol) WHERE e.snapshot_ref=$ref RETURN DISTINCT n.id,startNode(e).id", {"id": seed, "ref": ref})
            for neighbor, caller in call_neighbors:
                add(neighbor, issue_id, pr, commit, identity, "CALLS" if caller == seed else "CALLED_BY")
            # Bound same-file expansion; it is weaker evidence and never adds fix frequency.
            file_neighbors = graph.query("MATCH (f:File)-[a:CONTAINS]->(s:Symbol {id:$id}), (f)-[b:CONTAINS]->(n:Symbol) WHERE a.snapshot_ref=$ref AND b.snapshot_ref=$ref AND n.id <> s.id RETURN n.id ORDER BY n.id LIMIT 20", {"id": seed, "ref": ref})
            for (neighbor,) in file_neighbors:
                add(neighbor, issue_id, pr, commit, identity, "SAME_FILE")
    maximum = max((len(c["fix_issues"]) for c in candidates.values()), default=1) or 1
    ranked = []
    for candidate in candidates.values():
        candidate["paths"].sort(key=lambda p: (p["expansion"] is not None, p["expansion"] == "SAME_FILE", -p["similarity"], p["pr"]["number"], p["commit"]["sha"]))
        components = {"semantic_issue_similarity": candidate["similarity"], "historical_fix_frequency": len(candidate["fix_issues"])/maximum, "graph_proximity": candidate["proximity"], "recency": candidate["recency"], "call_graph_support": candidate["call_support"]}
        ranked.append({"symbol": candidate["symbol"], "score": round(score(components), 6), "components": components, "paths": candidate["paths"], "sources": sorted({p["pr"]["url"] for p in candidate["paths"]} | {p["issue"]["url"] for p in candidate["paths"]} | {p["commit"]["url"] for p in candidate["paths"]})})
    ranked.sort(key=lambda c: (-c["score"], c["symbol"]["id"]))
    logging.getLogger("whygraph.ranking").info("paths=%s candidates=%s weights=%s", len(rows), len(ranked), WEIGHTS)
    return ranked


def localize(graph, issue, as_of=None, k=8, limit=5):
    # Current investigations use the latest indexed state. Historical evaluation
    # passes its issue-creation cutoff explicitly and retains strict time filtering.
    at = cutoff(as_of)
    ref = ensure_snapshot(graph, at if as_of else None)
    text = issue.get("title", "") + "\n" + issue.get("body", "")
    try:
        neighbors = retrieve(graph, text, at, k=k, exclude=issue.get("id"))
    except ValueError:
        # A repository may be usable before optional embedding generation finishes.
        neighbors = []
    # A semantically adjacent issue is not enough to make its changed function a
    # recommendation. Require a stronger retrieval signal, and always search the
    # current source independently for ordinary (non-historical) investigations.
    from backend.agent.investigation import _terms
    query_terms = _terms(text)
    def relevant(item):
        issue_terms = _terms(item["issue"].get("title", "") + " " + item["issue"].get("body", ""))
        overlap = query_terms & issue_terms
        return item["similarity"] >= .35 and len(overlap) >= 2 and len(overlap) / max(1, len(query_terms)) >= .2
    relevant_neighbors = [item for item in neighbors if relevant(item)]
    candidates = rank(graph, relevant_neighbors, at, ref)
    direct_added = False
    from backend.repositories import repository_for_graph
    record = repository_for_graph(getattr(graph, "name", ""))
    if record and (as_of is not None or record["repository_id"] == "default" or record.get("indexed_ref") == ref):
        from backend.agent.investigation import search_code
        direct = search_code(record["repository_id"], text, limit=limit, as_of=as_of)["results"]
        existing = {candidate["symbol"]["id"]: candidate for candidate in candidates}
        max_terms = max(1, max((item["score"] for item in direct), default=1))
        for evidence in direct:
            symbol = evidence["symbol"]
            normalized = min(1.0, evidence["score"] / max_terms)
            if symbol["id"] in existing:
                candidate = existing[symbol["id"]]
                candidate["direct_evidence"] = evidence
                candidate["origin"] = "code_and_history"
                candidate["score"] = round(.8 * normalized + .2 * candidate["score"], 6)
                candidate["sources"] = sorted(set(candidate["sources"] + [evidence["source_url"]]))
            else:
                components = {"direct_code_score": normalized, "semantic_issue_similarity": 0.0, "historical_fix_frequency": 0.0, "graph_proximity": 0.0, "recency": 1.0, "call_graph_support": 0.0}
                candidate = {"symbol": symbol, "score": round(.8 * normalized, 6), "components": components, "paths": [], "sources": [evidence["source_url"]], "direct_evidence": evidence, "origin": "historical_code" if as_of else "current_code"}
                candidates.append(candidate)
                direct_added = True
        candidates.sort(key=lambda c: (-c["score"], c["symbol"]["id"]))
    return {"as_of": at, "snapshot_ref": ref, "weights": WEIGHTS, "ranking": {"direct": "0.8 * normalized source score", "combined": "0.8 * normalized source score + 0.2 * historical score", "historical": WEIGHTS}, "historical_issues": [{"issue": {k: n["issue"][k] for k in ("id", "number", "title", "url")}, "similarity": n["similarity"]} for n in relevant_neighbors], "candidates": candidates[:limit], "confidence": "low" if not candidates or candidates[0]["components"]["semantic_issue_similarity"] < .3 else "medium", "trace": ["FalkorDB issue vector retrieval with weak matches excluded", "Current source symbol retrieval runs independently" if as_of is None else "Explicit historical cutoff: source and history remain time-filtered", "Issue <- CLOSES - PR -> Commit -> MODIFIED_SYMBOL -> Symbol", "cutoff source snapshot: " + ref, "bounded CALLS/reverse CALLS/same-file expansion", "transparent ranking; scores are not probabilities"], "note": "Scores are ranking signals, not calibrated probabilities.", "direct_code_candidates_added": direct_added}
