"""Stop at the milestone-4 gate unless five real, source-verifiable paths exist."""
import json
from backend.config import ROOT, settings
from backend.graph.client import Graph
from backend.ingestion.git_history import git, source_at
from backend.ingestion.code_parser import parse_sources
from backend.ingestion.diff_mapper import map_symbols


def main():
    graph = Graph()
    rows = graph.query("MATCH (i:Issue)<-[:CLOSES]-(p:PullRequest)-[:CONTAINS_COMMIT]->(c:Commit)-[m:MODIFIED_SYMBOL]->(s:Symbol) RETURN i.number,p.number,c.sha,s.file_path,s.id,s.qualified_name,i.url,p.url,c.url ORDER BY p.number")
    verified, seen = [], set()
    for issue, pr, sha, path, identity, name, issue_url, pr_url, commit_url in rows:
        if issue in seen:
            continue
        parent = git(ROOT / ".data/repo", "rev-list", "--parents", "-n", "1", sha).split()[1]
        before = source_at(ROOT / ".data/repo", parent, path)
        after = source_at(ROOT / ".data/repo", sha, path)
        diff = git(ROOT / ".data/repo", "diff", "--unified=0", parent, sha, "--", path)
        old = parse_sources(settings.repo, {path: before}).symbols
        new = parse_sources(settings.repo, {path: after}).symbols
        if identity not in {m["symbol"]["id"] for m in map_symbols(diff, old, new)}:
            raise AssertionError(f"Invalid symbol mapping: {sha} {name}")
        seen.add(issue)
        verified.append({"issue": issue, "pr": pr, "commit": sha, "symbol": name, "sources": [issue_url, pr_url, commit_url], "diff": diff[:4000]})
        if len(verified) == 5:
            break
    if len(verified) < 5:
        raise RuntimeError(f"Only {len(verified)} verified symbol-changing issue fixes. Ingest more PRs before milestone 5.")
    output = ROOT / "evaluation/link-verification.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(verified, indent=2))
    graph.query("MATCH (r:Repository {id:$repo}) SET r.links_verified=true", {"repo": settings.repo})
    print(json.dumps(verified, indent=2))


if __name__ == "__main__":
    main()
