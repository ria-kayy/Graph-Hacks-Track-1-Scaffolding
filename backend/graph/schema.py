"""Explicit MVP schema. All nodes also have a canonical id for parameterized MERGE."""
NODE_PROPERTIES = {
    "TriagePreview": ["id", "repo", "issue_repo", "issue_number", "created_at", "expires_at", "issue_json", "result_json"],
    "Repository": ["id", "owner", "name", "url", "default_branch", "indexed_ref", "indexed_at"],
    "File": ["id", "path", "language", "content_hash"],
    "Symbol": ["id", "qualified_name", "name", "kind", "file_path", "start_line", "end_line", "docstring", "content_hash"],
    "Commit": ["id", "sha", "message", "author", "author_email", "timestamp", "url"],
    "PullRequest": ["id", "number", "title", "body", "state", "merged_at", "created_at", "url", "author"],
    "Issue": ["id", "number", "title", "body", "state", "created_at", "closed_at", "url", "author"],
    "Person": ["id", "login", "name"],
    "Claim": ["id", "text", "confidence", "valid_from", "valid_to", "created_at", "claim_type", "source_url", "source_author", "source_timestamp", "source_span"],
}
PROVENANCE_PROPERTIES = ["source_url", "source_type", "timestamp", "confidence"]
# Structural relationships carry snapshot_ref; CONTAINS carries source metadata
# per revision. Issue embeddings carry availability timestamps and archive evidence.
