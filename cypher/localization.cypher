MATCH (i:Issue)<-[cl:CLOSES]-(p:PullRequest)-[pc:CONTAINS_COMMIT]->(c:Commit)-[m:MODIFIED_SYMBOL]->(s:Symbol)
WHERE i.id IN $issues AND i.created_at < $as_of
  AND p.created_at <= $as_of AND p.merged_at <= $as_of
  AND c.timestamp <= $as_of AND cl.timestamp <= $as_of
  AND pc.timestamp <= $as_of AND m.timestamp <= $as_of
RETURN i.id,p,c,s
