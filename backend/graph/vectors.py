"""Embeddings and HNSW indexes remain in FalkorDB; no external vector store."""
from functools import lru_cache
import os
from backend.config import ROOT, settings
from backend.graph.client import properties


@lru_cache(maxsize=1)
def model():
    os.environ.setdefault("HF_HOME", str(ROOT / ".data/huggingface"))
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".data/matplotlib"))
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embedding_model, revision=os.getenv("EMBEDDING_REVISION") or None)


def embed(texts):
    return model().encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def index_embeddings(graph, labels=("Issue", "Symbol")):
    count = 0
    dimension = model().get_sentence_embedding_dimension()
    existing = graph.query("CALL db.indexes()")
    for label in labels:
        if not any(label in str(row) and "embedding" in str(row) and "VECTOR" in str(row) for row in existing):
            graph.query(f"CREATE VECTOR INDEX FOR (n:{label}) ON (n.embedding) OPTIONS {{dimension:{int(dimension)}, similarityFunction:'cosine'}}")
        rows = graph.query(f"MATCH (n:{label}) RETURN n")
        for offset in range(0, len(rows), 64):
            nodes = [properties(row[0]) for row in rows[offset:offset+64]]
            texts = [(n.get("original_title", n.get("title", "")) + "\n" + n.get("original_body", n.get("body", ""))) if label == "Issue" else (n["qualified_name"] + "\n" + n.get("docstring", "") + "\n" + n.get("body_summary", "")) for n in nodes]
            vectors = embed(texts)
            graph.query(f"UNWIND $rows AS row MATCH (n:{label} {{id:row.id}}) SET n.embedding=vecf32(row.vector), n.embedding_model=$model, n.embedding_available_at=row.available_at, n.embedding_source=row.source", {"rows": [{"id": n["id"], "vector": v, "available_at": n["created_at"] if "original_body" in n else n.get("updated_at"), "source": "original_opening" if "original_body" in n else "current"} for n, v in zip(nodes, vectors)], "model": settings.embedding_model})
            count += len(nodes)
    return count


def retrieve(graph, text, as_of, k=8, exclude=None):
    total = graph.query("MATCH (i:Issue) WHERE i.embedding IS NOT NULL RETURN count(i)")[0][0]
    if not total:
        raise ValueError("No issue embeddings; run scripts.embed_graph first")
    # Query the whole MVP corpus BEFORE time filtering. Future neighbors cannot crowd
    # historical neighbors out of a fixed ANN shortlist. HNSW is still approximate.
    # The implementation yields COSINE DISTANCE (1-cosine), verified against
    # proc_vector_query.c and a live identical-vector test. Lower is better.
    rows = graph.query("CALL db.idx.vector.queryNodes('Issue','embedding',$total,vecf32($vector)) YIELD node,score WHERE node.created_at < $at AND coalesce(node.embedding_available_at,node.updated_at) <= $at AND node.id <> $exclude RETURN node,score ORDER BY score ASC LIMIT $k", {"total": total, "vector": embed([text])[0], "at": as_of, "exclude": exclude or "", "k": max(1, min(k, 100))})
    output = []
    for node, distance in rows:
        issue = properties(node)
        if issue.get("original_title"):
            issue["title"], issue["body"] = issue["original_title"], issue["original_body"]
        output.append({"issue": issue, "similarity": max(0.0, min(1.0, 1.0-float(distance))), "distance": float(distance)})
    return output
