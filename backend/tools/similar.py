from backend.graph.client import properties
from backend.graph.vectors import retrieve
from backend.tools.common import cutoff
from backend.tools.localize import historical_fixes


def similar_issues(graph, text, as_of=None, k=8):
    at = cutoff(as_of)
    neighbors = retrieve(graph, text, at, k=k)
    for neighbor in neighbors:
        links = historical_fixes(graph, [neighbor], at)
        neighbor["fixes"] = []
        for _, p, c, s in links:
            pr = properties(p)
            if pr.get("updated_at", at) > at:
                for field in ("body", "title", "comments_json", "state"):
                    pr.pop(field, None)
            neighbor["fixes"].append({"pr": pr, "commit": properties(c), "symbol": {k: s.properties[k] for k in ("id", "qualified_name", "file_path")}})
        # Avoid returning present-day issue state/body in an as-of response.
        neighbor["issue"] = {k: neighbor["issue"][k] for k in ("id", "number", "title", "url", "created_at")}
    return {"as_of": at, "issues": neighbors}
