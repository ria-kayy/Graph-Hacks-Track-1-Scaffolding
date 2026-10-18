from backend.graph.queries import query
from backend.graph.client import properties
from backend.graph.snapshots import ensure_snapshot, symbol_metadata
from backend.tools.common import cutoff, resolve


def impact(graph, symbol, as_of=None):
    identity = resolve(graph, symbol)
    at = cutoff(as_of)
    ref = ensure_snapshot(graph, at if as_of else None)
    rows = graph.query(query("impact"), {"symbol": identity, "snapshot": ref})
    callers = [{"symbol": symbol_metadata(graph, node.properties["id"], ref) or {k: node.properties[k] for k in ("id", "qualified_name", "file_path")}, "path": path, "depth": len(path)-1} for node, path in rows]
    return {"symbol": identity, "as_of": at, "snapshot_ref": ref, "direct_callers": [c for c in callers if c["depth"] == 1], "transitive_callers": callers, "impacted_files": sorted({c["symbol"]["file_path"] for c in callers}), "depth_limit": 3, "path_limit": 100, "possibly_truncated": len(rows) == 100}
