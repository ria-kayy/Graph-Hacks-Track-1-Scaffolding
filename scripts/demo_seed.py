"""Optional, explicitly synthetic temporal demo in a separate graph."""
from backend.graph.client import Graph, edge
from backend.graph.temporal import supersede


if __name__ == "__main__":
    graph = Graph("whygraph_temporal_demo")
    graph.nodes("Symbol", [{"id": "demo:refresh_token", "qualified_name": "demo.refresh_token", "kind": "function"}])
    graph.nodes("Claim", [{"id": "demo:redis", "text": "Synthetic demo: refresh tokens are stored in Redis.", "subject_id": "demo:refresh_token", "created_at": "2020-01-01T00:00:00Z", "valid_from": "2020-01-01T00:00:00Z", "source_url": "https://example.org/synthetic-before", "confidence": 1.0}, {"id": "demo:jwt", "text": "Synthetic demo: refresh tokens are stateless JWTs.", "subject_id": "demo:refresh_token", "created_at": "2021-01-01T00:00:00Z", "valid_from": "2021-01-01T00:00:00Z", "source_url": "https://example.org/synthetic-after", "confidence": 1.0}])
    graph.edges("Claim", "EXPLAINS", "Symbol", [edge("demo:redis", "demo:refresh_token", "demo:redis"), edge("demo:jwt", "demo:refresh_token", "demo:jwt")])
    print("SYNTHETIC demonstration only:", supersede(graph, "demo:jwt", "demo:redis"))
