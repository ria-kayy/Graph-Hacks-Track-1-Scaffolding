from collections import OrderedDict
from backend.graph.client import properties


def dataset(graph, size=20):
    verified = graph.query("MATCH (r:Repository) RETURN r.links_verified")
    if not verified or not verified[0][0]:
        raise ValueError("Run scripts.verify_links before evaluation")
    rows = graph.query("MATCH (i:Issue)<-[:CLOSES]-(p:PullRequest)-[:CONTAINS_COMMIT]->(c:Commit)-[:MODIFIED_SYMBOL]->(s:Symbol) WHERE i.state='closed' AND p.merged_at IS NOT NULL AND p.merged_at > i.created_at AND s.kind <> 'class' RETURN i,p,s.id ORDER BY i.created_at,p.merged_at,s.id")
    cases = OrderedDict()
    for issue, pr, symbol in rows:
        i, p = properties(issue), properties(pr)
        if i.get("original_unavailable_reason"):
            continue
        if "original_body" not in i:
            raise ValueError(f"Recover original issue #{i['number']} with scripts.archive_issue_text before evaluation")
        i["title"], i["body"] = i["original_title"], i["original_body"]
        case = cases.setdefault(i["id"], {"issue": i, "fix_pr": {"number": p["number"], "url": p["url"], "merged_at": p["merged_at"]}, "actual": set()})
        if case["fix_pr"]["number"] == p["number"]:
            case["actual"].add(symbol)
    if len(cases) < size:
        raise ValueError(f"Only {len(cases)} eligible cases; need {size}. Ingest more merged fixes.")
    return [{**case, "actual": sorted(case["actual"])} for case in list(cases.values())[:size]]
