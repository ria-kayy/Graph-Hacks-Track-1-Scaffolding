import math
import re
from collections import Counter
from backend.graph.client import properties
from backend.tools.localize import historical_fixes
from backend.graph.snapshots import symbol_metadata, relocated_symbol


def tokens(text):
    return re.findall(r"[a-z][a-z0-9_]+", text.lower())


def lexical_neighbors(graph, text, at, exclude=None, k=8):
    nodes = [properties(r[0]) for r in graph.query("MATCH (i:Issue) WHERE i.created_at < $at AND coalesce(i.embedding_available_at,i.updated_at) <= $at AND i.id <> $exclude RETURN i", {"at": at, "exclude": exclude or ""})]
    for node in nodes:
        if "original_title" in node:
            node["title"], node["body"] = node["original_title"], node["original_body"]
    docs = [Counter(tokens(n["title"] + " " + n["body"])) for n in nodes]
    frequency = Counter(term for doc in docs for term in doc)
    average = sum(sum(d.values()) for d in docs)/len(docs) if docs else 1
    query_terms = set(tokens(text))
    ranked = []
    for node, doc in zip(nodes, docs):
        value = 0
        length = sum(doc.values())
        for term in query_terms:
            tf = doc[term]
            if tf:
                idf = math.log(1+(len(docs)-frequency[term]+.5)/(frequency[term]+.5))
                value += idf*tf*2.2/(tf+1.2*(.25+.75*length/max(average, 1)))
        if value:
            ranked.append({"issue": node, "similarity": value})
    ranked.sort(key=lambda n: (-n["similarity"], n["issue"]["id"]))
    return ranked[:k]


def direct_predictions(graph, neighbors, at, ref):
    """Both baselines project retrieved fixes to functions, with no graph expansion."""
    scores = Counter()
    similarities = {n["issue"]["id"]: n["similarity"] for n in neighbors}
    seen = set()
    for issue_id, _, _, node in historical_fixes(graph, neighbors, at):
        identity = node.properties["id"]
        if not symbol_metadata(graph, identity, ref):
            identity, _ = relocated_symbol(graph, identity, ref, at)
        if not identity:
            continue
        metadata = symbol_metadata(graph, identity, ref)
        if not metadata or metadata["kind"] == "class" or (issue_id, identity) in seen:
            continue
        seen.add((issue_id, identity))
        scores[identity] += similarities[issue_id]
    return [identity for identity, _ in sorted(scores.items(), key=lambda row: (-row[1], row[0]))[:5]]
