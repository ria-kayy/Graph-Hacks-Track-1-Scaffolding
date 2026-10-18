import os
import uuid
import pytest
from backend.graph.client import Graph
from backend.graph.temporal import supersede


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("WHYGRAPH_INTEGRATION") != "1", reason="requires real FalkorDB")
def test_supersession_ends_only_same_subject_old_claim():
    graph = Graph("whygraph_test_" + uuid.uuid4().hex)
    try:
        graph.nodes("Claim", [{"id": "old", "subject_id": "symbol:a", "valid_from": "2020-01-01T00:00:00Z", "source_url": "https://example.org/old", "confidence": .8}, {"id": "new", "subject_id": "symbol:a", "valid_from": "2021-01-01T00:00:00Z", "source_url": "https://example.org/new", "confidence": .8}, {"id": "other", "subject_id": "symbol:b", "valid_from": "2022-01-01T00:00:00Z"}])
        with pytest.raises(ValueError, match="same subject"):
            supersede(graph, "other", "old")
        assert supersede(graph, "new", "old")["old_valid_to"] == "2021-01-01T00:00:00Z"
        assert graph.query("MATCH (new:Claim {id:'new'})-[:SUPERSEDES]->(old:Claim {id:'old'}) RETURN old.valid_to") == [["2021-01-01T00:00:00Z"]]
    finally:
        graph.graph.delete()
