import pytest
from backend.ingestion.claims import validate_claim, rule_extract


def test_claim_rejects_fabricated_quote():
    with pytest.raises(ValueError, match="absent"):
        validate_claim({"text": "Use Redis because it is safer.", "source_span": "Use Redis because it is safer.", "confidence": .8}, "The database stores metadata.")


def test_claim_rejects_paraphrase_as_quote():
    with pytest.raises(ValueError, match="equal"):
        validate_claim({"text": "This is a paraphrase of the evidence.", "source_span": "The old implementation caused stalled progress bars.", "confidence": .8}, "The old implementation caused stalled progress bars.")


def test_rule_extract_exact_high_information_span():
    source = "Fixes #12. We update after yielding because the work happens inside the loop."
    claim = rule_extract(source)[0]
    assert validate_claim(claim, source).source_span in source
