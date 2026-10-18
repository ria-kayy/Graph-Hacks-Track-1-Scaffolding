"""Repository-scoped, retrieval-only investigation with verified code evidence."""
import hashlib
import re
import threading
import uuid
import json
import subprocess

from backend.graph.client import Graph, properties
from backend.repositories import context, get_repository
from backend.tools.common import cutoff, snapshot
from backend.agent.evidence import read_revision, source_evidence, validate_evidence

_conversations: dict[str, dict] = {}
_lock = threading.Lock()


def _terms(text: str) -> set[str]:
    words = {x.lower() for x in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text) if x.lower() not in {"the", "and", "for", "where", "does", "with", "this", "that", "from", "have", "what", "why", "which", "after", "before", "while", "not", "can", "could", "should", "would", "are", "was", "were", "been", "has", "had", "how", "when", "then", "them", "those", "its", "into", "each", "our", "your", "you", "code", "function", "functions", "implemented", "implementation", "changed", "change", "previously", "please", "find", "about", "there", "here"}}
    aliases = {"update": {"advance", "refresh", "render", "redraw"}, "progress": {"bar", "iterator", "generator", "iteration"}, "generator": {"yield", "iterator", "iteration"}, "running": {"loop", "process", "yield", "item"}, "retry": {"attempt", "backoff", "retries"}, "authentication": {"auth", "token", "login", "credential"}}
    for word in tuple(words):
        words.update(aliases.get(word, ()))
    return words


def search_code(repo_id: str, query_text: str, limit: int = 6, as_of: str | None = None) -> dict:
    record = get_repository(repo_id)
    ctx = context(repo_id)
    if record.get("status") in ("queued", "indexing", "failed"):
        raise ValueError("Repository is not ready; inspect its ingestion status and refresh if needed")
    graph = Graph(ctx.graph_name)
    if as_of:
        as_of = cutoff(as_of)
        from backend.graph.snapshots import ensure_snapshot
        ref = ensure_snapshot(graph, as_of)
    else:
        from backend.tools.common import snapshot
        ref = record.get("indexed_ref") or snapshot(graph)
    if not ref:
        raise ValueError("Repository indexing has not completed")
    from backend.ingestion.code_parser import ensure_search_fields
    ensure_search_fields(graph, ctx, ref)
    terms = sorted(_terms(query_text))[:64]
    errors = sorted({token.lower() for token in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:Error|Exception)\b", query_text)})[:16]
    vectors = []
    try:
        from backend.graph.vectors import embed
        if not as_of:
            total = graph.query("MATCH (s:Symbol) WHERE s.embedding IS NOT NULL RETURN count(s)")[0][0]
            if total:
                # Filter the snapshot before limiting results; return only the
                # vector shortlist, never the full symbol corpus to Python.
                vector_rows = graph.query("CALL db.idx.vector.queryNodes('Symbol','embedding',$total,vecf32($vector)) YIELD node,score MATCH ()-[e:CONTAINS]->(node) WHERE e.snapshot_ref=$ref RETURN node.id,score ORDER BY score ASC LIMIT 20", {"total": total, "vector": embed([query_text])[0], "ref": ref})
                vectors = [{"id": identity, "similarity": max(0.0, min(1.0, 1.0-float(distance)))} for identity, distance in vector_rows]
    except Exception:
        # Embeddings are optional; lexical search covers the entire snapshot.
        vectors = []
    count = max(1, min(limit, 10))
    rows = graph.query("""
        MATCH ()-[e:CONTAINS]->(s:Symbol)
        WHERE e.snapshot_ref=$ref
        WITH s,e,
          reduce(value=0, term IN $terms | value +
            CASE WHEN e.search_text CONTAINS term THEN 1 ELSE 0 END +
            CASE WHEN e.search_names CONTAINS term THEN 2 ELSE 0 END) AS lexical,
          reduce(value=0, term IN $errors | value +
            CASE WHEN e.search_text CONTAINS term THEN 3 ELSE 0 END) AS error_hits,
          reduce(value=0.0, hit IN $vectors |
            CASE WHEN hit.id=s.id THEN hit.similarity ELSE value END) AS vector_similarity
        WHERE lexical > 0 OR error_hits > 0 OR vector_similarity >= 0.35
        WITH s,e,vector_similarity,
          (lexical + error_hits + 2 * vector_similarity) *
          CASE WHEN e.search_kind='class' THEN 0.75 ELSE 1.0 END AS ranking_score
        RETURN s.id,e.search_metadata_json,ranking_score,vector_similarity
        ORDER BY ranking_score DESC,s.id ASC LIMIT $pool
    """, {"ref": ref, "terms": terms, "errors": errors, "vectors": vectors, "pool": count * 3})
    evidence, sources = [], {}
    for identity, metadata_json, score, vector_score in rows:
        if len(evidence) >= count:
            break
        symbol = json.loads(metadata_json)
        path = symbol.get("file_path", "")
        try:
            if path not in sources:
                sources[path] = read_revision(ctx, ref, path)
            source = sources[path]
            lines = source.splitlines()
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
            continue
        start = max(1, int(symbol.get("start_line", 1)))
        symbol_end = min(len(lines), int(symbol.get("end_line", start)))
        if start > len(lines) or symbol_end < start:
            continue
        end = min(symbol_end, start + 79)
        symbol_source = "\n".join(lines[start-1:symbol_end]).lower()
        matched = [term for term in terms if term in symbol_source or term in symbol.get("qualified_name", "").lower() or term in path.lower()]
        evidence.append(source_evidence(ctx, ref, path, source, start, end, symbol,
                                        score=round(score, 4), vector_similarity=round(vector_score, 4),
                                        matched_terms=matched))
    return {"repository_id": repo_id, "revision": ref, "results": evidence}


def search_commits(repo_id: str, query_text: str, as_of: str | None = None, limit: int = 10) -> list[dict]:
    record = get_repository(repo_id)
    graph = Graph(context(repo_id).graph_name)
    at = cutoff(as_of)
    terms = sorted(_terms(query_text))[:20]
    if not terms:
        return []
    clauses = " OR ".join(f"toLower(c.message) CONTAINS ${'term'+str(i)}" for i in range(len(terms)))
    params = {f"term{i}": term for i, term in enumerate(terms)}
    params.update({"at": at, "limit": max(1, min(limit, 20))})
    relevance = " + ".join(f"CASE WHEN toLower(c.message) CONTAINS $term{i} THEN 1 ELSE 0 END" for i in range(len(terms)))
    rows = graph.query(f"MATCH (c:Commit) WHERE c.timestamp <= $at AND ({clauses}) WITH c, ({relevance}) AS relevance RETURN c ORDER BY relevance DESC,c.timestamp DESC LIMIT $limit", params)
    return [properties(row[0]) for row in rows]


def symbol_context(graph: Graph, identity: str, ref: str) -> dict:
    callees = graph.query("MATCH (s:Symbol {id:$id})-[e:CALLS]->(n:Symbol) WHERE e.snapshot_ref=$ref RETURN n.qualified_name,n.file_path LIMIT 12", {"id": identity, "ref": ref})
    callers = graph.query("MATCH (n:Symbol)-[e:CALLS]->(s:Symbol {id:$id}) WHERE e.snapshot_ref=$ref RETURN n.qualified_name,n.file_path LIMIT 12", {"id": identity, "ref": ref})
    return {"callers": [{"qualified_name": name, "file_path": path} for name, path in callers], "callees": [{"qualified_name": name, "file_path": path} for name, path in callees], "snapshot_ref": ref}


def investigate(repo_id: str, query_text: str, conversation_id: str | None = None, as_of: str | None = None, context_text: str = "") -> dict:
    query_text = query_text.strip()
    if not query_text or len(query_text) > 10000:
        raise ValueError("Enter a question between 1 and 10,000 characters")
    if as_of:
        as_of = cutoff(as_of)
    with _lock:
        prior = _conversations.get(conversation_id) if conversation_id else None
        if prior and prior["repository_id"] != repo_id:
            raise ValueError("Conversation belongs to a different repository")
        if not conversation_id or not prior:
            conversation_id = uuid.uuid4().hex
        if prior and re.search(r"\b(it|that|those|they|there|them|last year|previously)\b", query_text, re.I):
            query_for_retrieval = prior.get("retrieval_query", prior["query"]) + "\n" + " ".join(x["qualified_name"] for x in prior.get("symbols", [])) + "\n" + query_text
        else:
            query_for_retrieval = query_text
    if context_text:
        query_for_retrieval += "\n" + context_text[:3000]
    found = search_code(repo_id, query_for_retrieval, as_of=as_of)
    candidates = found["results"]
    evidence = list(candidates)
    symbols = [item["symbol"] for item in candidates]
    findings = []
    for index, item in enumerate(candidates):
        context_result = symbol_context(Graph(context(repo_id).graph_name), item["symbol_id"], found["revision"]) if index < 3 else {"callers": [], "callees": [], "snapshot_ref": found["revision"]}
        historical_record = None
        if index < 3:
            try:
                from backend.tools.history import history
                historical_record = history(Graph(context(repo_id).graph_name), item["symbol_id"], as_of)
            except ValueError:
                pass
        findings.append({"symbol": item["symbol"], "score": item["score"], "evidence_ids": [item["evidence_id"]], "reason": "Source matches " + ", ".join(item.get("matched_terms", [])[:8]) + f" (ranking score {item['score']}); inspect the cited implementation.", "structure": context_result, "history": historical_record})
    historical = []
    graph = Graph(context(repo_id).graph_name)
    try:
        from backend.tools.similar import similar_issues
        hits = similar_issues(graph, query_for_retrieval, as_of)
        # Similarity is background only here; no issue match is promoted to causal proof.
        historical = [{"issue": h["issue"], "similarity": h["similarity"], "relationship": "semantic historical match; not verified as causal evidence"} for h in hits.get("issues", [])[:3]]
    except Exception:
        historical = []
    commits = search_commits(repo_id, query_for_retrieval, as_of, limit=8)
    for commit in commits:
        links = graph.query("MATCH (p:PullRequest)-[pc:CONTAINS_COMMIT]->(c:Commit {id:$sha}) WHERE p.created_at <= $at AND p.merged_at <= $at AND pc.timestamp <= $at OPTIONAL MATCH (p)-[cl:CLOSES]->(i:Issue) WHERE i.created_at <= $at AND cl.timestamp <= $at RETURN p,i", {"sha": commit["sha"], "at": cutoff(as_of)})
        changed = graph.query("MATCH (c:Commit {id:$sha})-[m:MODIFIED_SYMBOL]->(s:Symbol) WHERE m.timestamp <= $at RETURN DISTINCT s.qualified_name,s.file_path LIMIT 20", {"sha": commit["sha"], "at": cutoff(as_of)})
        commit["verified_paths"] = [{"pr": _historical_entity(pr, as_of), "issue": _historical_entity(issue, as_of)} for pr, issue in links]
        commit["modified_symbols"] = [{"qualified_name": name, "file_path": path} for name, path in changed]
        evidence.append({"evidence_id": hashlib.sha256(f"{repo_id}:{commit['sha']}:commit".encode()).hexdigest()[:24], "repository_id": repo_id, "evidence_type": "commit", "source_url": commit["url"], "commit_sha": commit["sha"], "timestamp": commit["timestamp"], "excerpt": commit["message"], "relationship": "lexical commit-message match; historical background only", "score": 0.0, "verified_paths": commit["verified_paths"], "modified_symbols": commit["modified_symbols"]})
    for finding in findings:
        if finding["history"]:
            hist = finding["history"]
            evidence.extend(hist.get("evidence", []))
            finding["history"] = {"symbol": hist["symbol"], "as_of": hist["as_of"], "timeline": hist["timeline"][:5], "claims": hist["claims"][:3], "sources": hist["sources"][:8], "note": hist["note"]}
    if candidates:
        answer = "Retrieval-only investigation found source candidates in the selected indexed snapshot. The code citations are verified against that revision; historical matches below are background and do not establish the cause."
    else:
        answer = "No current source candidate matched strongly enough to cite. Try adding an error message or a short description of the observed behavior."
    with _lock:
        _conversations[conversation_id] = {"repository_id": repo_id, "query": query_text, "retrieval_query": query_for_retrieval[-6000:], "symbols": symbols[:5]}
        if len(_conversations) > 500:
            _conversations.pop(next(iter(_conversations)))
    mode = "retrieval_only"
    trace = ["Use " + ("the source snapshot at " + found["revision"] if as_of else "the current indexed repository snapshot"), "Hybrid lexical and optional vector search over symbol names, paths, docstrings and source summaries", "Verify source spans against isolated checkout at the indexed revision", "Retrieve historical issues as non-causal background"]
    # Verify all citations before exposing them to a provider or client.
    evidence, rejected = validate_evidence(evidence, context(repo_id), found["revision"], as_of)
    valid_ids = {item["evidence_id"] for item in evidence}
    findings = [f for f in findings if set(f["evidence_ids"]).issubset(valid_ids)]
    executed_tools = ["search_code", "search_commits"]
    if historical:
        executed_tools.append("similar_issues")
    if findings:
        executed_tools += ["get_symbol_context", "history"]
    if rejected:
        trace.append(f"Rejected {len(rejected)} citations that failed source verification")
    try:
        from backend.agent.planner import run
        synthesis = run(repo_id, query_for_retrieval, as_of, evidence, findings)
        if synthesis:
            verified, rejected = validate_evidence(synthesis["evidence"], context(repo_id), found["revision"], as_of)
            if rejected:
                raise ValueError("Model cited invalid source evidence")
            answer = synthesis["answer"]
            evidence = verified
            executed_tools += synthesis["tools"]
            trace += synthesis["trace"]
            mode = "model_assisted"
    except Exception:
        trace.append("Configured LLM unavailable or returned invalid citations; use retrieval-only fallback")
    if not findings and mode == "retrieval_only":
        answer = "No verified source candidate is available. Add an error message or a more specific description to continue investigating."
    if mode == "retrieval_only":
        trace.append("No validated model synthesis; retrieval-only mode")
    return {"answer": answer, "mode": mode, "repository_id": repo_id, "revision": found["revision"], "conversation_id": conversation_id, "interpretation": query_text, "uncertainty": "Search candidates are investigation starting points. No runtime failure or root cause has been reproduced.", "suggested_next_step": "Inspect the cited implementation and its callers with the reported input; compare historical changes only when the behavior agrees.", "findings": findings, "evidence": evidence, "historical_matches": historical, "commit_matches": commits, "tools_used": list(dict.fromkeys(executed_tools)) + (["configured_llm"] if mode == "model_assisted" else []), "trace": trace + ["Expand top code candidates to callers, callees, and time-valid function history"]}


def _historical_entity(node, as_of):
    entity = properties(node)
    if entity and as_of and entity.get("updated_at", cutoff(as_of)) > cutoff(as_of):
        for field in ("title", "body", "comments_json", "state"):
            entity.pop(field, None)
    return entity


def read_source(repo_id: str, file_path: str, start_line: int = 1, end_line: int | None = None, as_of: str | None = None) -> dict:
    from backend.graph.snapshots import ensure_snapshot
    ctx = context(repo_id)
    graph = Graph(ctx.graph_name)
    ref = ensure_snapshot(graph, cutoff(as_of) if as_of else None)
    # Only paths recorded by the source parser in this snapshot are available.
    rows = graph.query("MATCH (:Repository)-[e:HAS_FILE]->(f:File) WHERE f.path=$path AND e.snapshot_ref=$ref RETURN f.id LIMIT 1", {"path": file_path, "ref": ref})
    if not rows:
        raise ValueError("File is not indexed in the selected snapshot")
    source = read_revision(ctx, ref, file_path)
    end = min(end_line or start_line + 79, start_line + 199, len(source.splitlines()))
    return source_evidence(ctx, ref, file_path, source, start_line, end)


def get_symbol_context(repo_id: str, symbol: str, as_of: str | None = None) -> dict:
    from backend.graph.snapshots import ensure_snapshot, symbol_metadata
    from backend.tools.common import resolve
    graph = Graph(context(repo_id).graph_name)
    ref = ensure_snapshot(graph, cutoff(as_of) if as_of else None)
    identity = resolve(graph, symbol)
    metadata = symbol_metadata(graph, identity, ref)
    if not metadata:
        raise ValueError("Symbol is absent from the selected snapshot")
    return {"symbol": metadata, **symbol_context(graph, identity, ref)}
