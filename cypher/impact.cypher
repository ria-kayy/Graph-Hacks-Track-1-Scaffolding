MATCH path=(caller:Symbol)-[:CALLS*1..3]->(target:Symbol {id:$symbol})
WHERE all(e IN relationships(path) WHERE e.snapshot_ref=$snapshot)
RETURN caller, [s IN nodes(path) | s.qualified_name] AS path
LIMIT 100
