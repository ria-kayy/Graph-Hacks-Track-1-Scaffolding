"""The only persistent context store. All values are parameterized."""
import json
import logging
import time
import threading
from functools import lru_cache
from backend.config import settings

log = logging.getLogger("whygraph.graph")
LABELS = {"Repository", "File", "Symbol", "Commit", "PullRequest", "Issue", "Person", "Claim", "TriagePreview"}
RELATIONS = {"HAS_FILE", "CONTAINS", "CALLS", "IMPORTS", "MODIFIED", "MODIFIED_SYMBOL", "CONTAINS_COMMIT", "CLOSES", "AUTHORED", "OPENED", "REVIEWED", "EXPLAINS", "SUPPORTED_BY", "SUPERSEDES"}


_connection_lock = threading.Lock()


@lru_cache(maxsize=4)
def _connection(mode, lite_path, host, port, password):
    if mode == "lite":
        from pathlib import Path
        from redislite.falkordb_client import FalkorDB
        Path(lite_path).parent.mkdir(parents=True, exist_ok=True)
        return FalkorDB(lite_path)
    from falkordb import FalkorDB
    return FalkorDB(host=host, port=port, password=password, socket_connect_timeout=5, socket_timeout=35)


class Graph:
    def __init__(self, name=None):
        # Share the connection runtime, especially the embedded server lifecycle.
        # Each graph still owns its driver schema and isolated graph namespace.
        with _connection_lock:
            self.db = _connection(settings.mode, settings.lite_path, settings.host, settings.port, settings.password)
        self.name = name or settings.graph
        self.graph = self.db.select_graph(self.name)

    def query(self, cypher, params=None):
        start = time.monotonic()
        result = self.graph.query(cypher, params or {}, timeout=30000)
        rows = result.result_set
        log.info(json.dumps({"operation": "graph_query", "elapsed_ms": round((time.monotonic()-start)*1000, 2), "rows": len(rows), **({"cypher": cypher} if settings.debug else {})}))
        return rows

    def nodes(self, label, values):
        if label not in LABELS:
            raise ValueError("Unknown node label")
        for offset in range(0, len(values), 200):
            self.query(f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row", {"rows": values[offset:offset+200]})

    def edges(self, source, relation, target, values):
        if source not in LABELS or target not in LABELS or relation not in RELATIONS:
            raise ValueError("Unknown graph type")
        for offset in range(0, len(values), 200):
            self.query(f"UNWIND $rows AS row MATCH (a:{source} {{id: row.a}}), (b:{target} {{id: row.b}}) MERGE (a)-[e:{relation} {{key: row.key}}]->(b) SET e += row.props", {"rows": values[offset:offset+200]})

    def initialize(self):
        existing = self.query("CALL db.indexes()")
        # Initialization is rerunnable; inspect existing indexes instead of swallowing errors.
        for label in sorted(LABELS):
            if not any(label in str(row) and "id" in str(row) for row in existing):
                self.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")


def edge(a, b, key, **props):
    return {"a": a, "b": b, "key": key, "props": props}


def properties(node):
    return {k: v for k, v in node.properties.items() if k != "embedding"} if node is not None else None
