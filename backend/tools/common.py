from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def cutoff(value=None):
    if not value:
        return now()
    message = "Enter a valid ISO timestamp with a timezone, for example 2026-10-04T00:00:00Z."
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(message) from exc
    if parsed.tzinfo is None:
        raise ValueError(message)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve(graph, symbol):
    rows = graph.query("MATCH (s:Symbol) WHERE s.id=$symbol OR s.qualified_name=$symbol RETURN s.id,s.qualified_name", {"symbol": symbol})
    if not rows:
        raise ValueError(f"Unknown symbol: {symbol}")
    if len(rows) > 1:
        current = graph.query("MATCH (r:Repository)-[:HAS_FILE]->(f:File)-[e:CONTAINS]->(s:Symbol) WHERE (s.id=$symbol OR s.qualified_name=$symbol) AND e.snapshot_ref=r.indexed_ref RETURN s.id", {"symbol": symbol})
        if len(current) == 1:
            return current[0][0]
        raise ValueError("Ambiguous historical name; use the full symbol ID")
    return rows[0][0]


def snapshot(graph):
    rows = graph.query("MATCH (r:Repository) RETURN r.indexed_ref")
    if not rows:
        raise ValueError("Repository has not been ingested")
    return rows[0][0]
