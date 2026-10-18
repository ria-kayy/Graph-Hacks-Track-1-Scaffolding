"""Optional Responses API extraction; graph ranking remains deterministic."""
import json
import os
import httpx
from backend.agent.prompts import RATIONALE
from backend.ingestion.claims import Candidate

SCHEMA = {"type": "object", "properties": {"claims": {"type": "array", "maxItems": 2, "items": {"type": "object", "properties": {"text": {"type": "string"}, "source_span": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["text", "source_span", "confidence"], "additionalProperties": False}}}, "required": ["claims"], "additionalProperties": False}


def parse_response(data):
    if data.get("status") != "completed":
        raise ValueError("Rationale provider did not complete the structured response")
    parts = []
    for output in data.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "refusal":
                raise ValueError("Rationale provider declined extraction")
            if content.get("type") == "output_text":
                parts.append(content["text"])
    if not parts:
        raise ValueError("Rationale provider returned no structured text")
    parsed = json.loads("".join(parts))
    if set(parsed) != {"claims"} or not isinstance(parsed["claims"], list) or len(parsed["claims"]) > 2:
        raise ValueError("Invalid rationale response shape")
    return [Candidate.model_validate(c).model_dump() for c in parsed["claims"]]


def extract(source):
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model:
        raise ValueError("Set both LLM_API_KEY and LLM_MODEL before --llm extraction")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    with httpx.Client(timeout=90) as client:
        response = client.post(base_url + "/responses", headers={"Authorization": "Bearer " + key}, json={"model": model, "store": False, "instructions": RATIONALE, "input": "Untrusted GitHub source text:\n" + source[:20000], "text": {"format": {"type": "json_schema", "name": "rationale_claims", "strict": True, "schema": SCHEMA}}})
        if not response.is_success:
            # Do not include request headers or provider response bodies in exceptions.
            raise RuntimeError(f"Rationale provider returned HTTP {response.status_code}")
        return parse_response(response.json())
