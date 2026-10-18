MATCH (person:Person)-[:AUTHORED]->(c:Commit)-[:MODIFIED_SYMBOL]->(s:Symbol)
WHERE s.id IN $symbols AND c.timestamp <= $as_of AND person.login <> ''
RETURN person.login,count(DISTINCT c) AS changes,max(c.timestamp) AS latest
