MATCH (s:Symbol)<-[:MODIFIED_SYMBOL]-(c:Commit)
WHERE s.id IN $symbols AND c.timestamp <= $as_of
OPTIONAL MATCH (p:PullRequest)-[pc:CONTAINS_COMMIT]->(c)
WHERE p.created_at <= $as_of AND p.merged_at <= $as_of AND pc.timestamp <= $as_of
OPTIONAL MATCH (p)-[cl:CLOSES]->(i:Issue)
WHERE i.created_at <= $as_of AND cl.timestamp <= $as_of
RETURN c,p,i,s ORDER BY c.timestamp DESC
