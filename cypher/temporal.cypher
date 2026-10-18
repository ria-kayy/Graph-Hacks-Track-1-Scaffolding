MATCH (c:Claim)-[:EXPLAINS]->(s:Symbol {id:$symbol})
WHERE c.created_at <= $as_of AND c.valid_from <= $as_of
  AND (c.valid_to IS NULL OR $as_of < c.valid_to)
RETURN c
