from datetime import datetime
from backend.tools.common import cutoff
from backend.graph.client import edge, properties


def is_current(claim, at):
    time = datetime.fromisoformat(cutoff(at).replace("Z", "+00:00"))
    start = datetime.fromisoformat(claim["valid_from"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(claim["valid_to"].replace("Z", "+00:00")) if claim.get("valid_to") else None
    return start <= time and (end is None or time < end)


def supersede(graph, new_id, old_id):
    if new_id == old_id:
        raise ValueError("A claim cannot supersede itself")
    rows = graph.query("MATCH (new:Claim {id:$new}), (old:Claim {id:$old}) RETURN new,old", {"new": new_id, "old": old_id})
    if not rows:
        raise ValueError("Both claims must exist")
    new, old = map(properties, rows[0])
    if new.get("subject_id") != old.get("subject_id") or not new.get("subject_id"):
        raise ValueError("Supersession requires claims about the same subject")
    if new["valid_from"] <= old["valid_from"]:
        raise ValueError("Superseding claim must be newer")
    # Contradiction is an explicit caller decision; never infer it from timestamps.
    graph.query("MATCH (new:Claim {id:$new}), (old:Claim {id:$old}) SET old.valid_to=new.valid_from MERGE (new)-[e:SUPERSEDES]->(old) SET e.source_url=new.source_url,e.timestamp=new.valid_from,e.confidence=new.confidence,e.source_type='explicit_supersession'", {"new": new_id, "old": old_id})
    return {"new": new_id, "old": old_id, "old_valid_to": new["valid_from"]}
