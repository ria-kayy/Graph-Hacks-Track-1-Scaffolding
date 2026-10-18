import json
import pytest
from backend.agent.llm import parse_response


def test_structured_provider_output_parsed_then_source_validated():
    candidate = {"text": "A workaround exists because old terminals behave differently.", "source_span": "A workaround exists because old terminals behave differently.", "confidence": .8}
    data = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"claims": [candidate]})}]}]}
    assert parse_response(data) == [candidate]


def test_refusal_and_incomplete_output_are_explicit_errors():
    with pytest.raises(ValueError, match="declined"):
        parse_response({"status": "completed", "output": [{"content": [{"type": "refusal"}]}]})
    with pytest.raises(ValueError, match="complete"):
        parse_response({"status": "incomplete"})
