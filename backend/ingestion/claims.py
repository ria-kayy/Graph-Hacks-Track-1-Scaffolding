"""Validated extractive rationale. A model can suggest spans, never invent evidence."""
import hashlib
import json
import re
from pydantic import BaseModel, Field
from backend.graph.client import edge, properties
from backend.tools.common import now, cutoff


class Candidate(BaseModel):
    text: str = Field(min_length=20, max_length=1200)
    source_span: str = Field(min_length=20, max_length=1200)
    confidence: float = Field(ge=0, le=1)


def validate_claim(candidate, source):
    candidate = Candidate.model_validate(candidate)
    if candidate.source_span not in source:
        raise ValueError("Rejected claim: source_span is absent from source text")
    # MVP is strictly extractive: paraphrases must not masquerade as direct quotes.
    if candidate.text != candidate.source_span:
        raise ValueError("Extracted claim text must equal its verified source span")
    return candidate


def rule_extract(source):
    suggestions = []
    for span in re.split(r"(?<=[.!?])\s+|\n\s*\n", source):
        if 35 <= len(span) <= 1000 and re.search(r"\b(?:because|workaround|cannot use|instead of|caused|in order to|so that)\b", span, re.I):
            suggestions.append({"text": span, "source_span": span, "confidence": .75})
            if len(suggestions) == 2:
                break
    return suggestions


def extract_claims(graph, extractor=None):
    extractor = extractor or rule_extract
    accepted, rejected = 0, []
    for label in ("Issue", "PullRequest"):
        for (node,) in graph.query(f"MATCH (n:{label}) RETURN n"):
            source = properties(node)
            records = [{"body": source.get("body", ""), "html_url": source["url"], "user": {"login": source["author"]}, "created_at": source.get("updated_at", source["created_at"])}]
            records += json.loads(source.get("comments_json", "[]"))
            for record in records:
                text = record.get("body") or ""
                source_url = record.get("html_url") or source["url"]
                timestamp = record.get("updated_at") or record.get("submitted_at") or record.get("created_at")
                if not timestamp:
                    continue
                for suggestion in extractor(text):
                    try:
                        claim = validate_claim(suggestion, text)
                    except ValueError as exc:
                        rejected.append({"source_url": source_url, "reason": str(exc)})
                        continue
                    identity = hashlib.sha256((source_url + claim.source_span).encode()).hexdigest()
                    # Extraction happened now; do not backdate created_at to pass eval cutoffs.
                    existing = graph.query("MATCH (c:Claim {id:$id}) RETURN c.created_at", {"id": identity})
                    created = existing[0][0] if existing else now()
                    author = (record.get("user") or {}).get("login", source["author"])
                    props = {"id": identity, **claim.model_dump(), "claim_type": "extracted", "valid_from": cutoff(timestamp), "created_at": created, "source_url": source_url, "source_author": author, "source_timestamp": cutoff(timestamp), "extraction_method": "rules" if extractor is rule_extract else "model", "subject_id": source["id"]}
                    graph.nodes("Claim", [props])
                    provenance = {"source_url": source_url, "source_type": "github_rationale", "timestamp": cutoff(timestamp), "confidence": claim.confidence}
                    graph.edges("Claim", "SUPPORTED_BY", label, [edge(identity, source["id"], identity, **provenance)])
                    graph.edges("Claim", "EXPLAINS", label, [edge(identity, source["id"], identity, **provenance)])
                    # Only directly name-matched symbols receive EXPLAINS edges.
                    if label == "PullRequest":
                        rows = graph.query("MATCH (p:PullRequest {id:$id})-[:CONTAINS_COMMIT]->(:Commit)-[:MODIFIED_SYMBOL]->(s:Symbol) RETURN DISTINCT s.id,s.name,s.qualified_name", {"id": source["id"]})
                        for symbol_id, name, qualified in rows:
                            if qualified in claim.text or re.search(r"\b" + re.escape(name) + r"\s*\(", claim.text):
                                graph.edges("Claim", "EXPLAINS", "Symbol", [edge(identity, symbol_id, identity, **provenance)])
                    accepted += 1
    return {"accepted": accepted, "rejected": rejected}
