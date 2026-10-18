import subprocess
from datetime import datetime, timezone
from pathlib import Path
from backend.graph.client import edge
from backend.ingestion.code_parser import parse_sources
from backend.ingestion.diff_mapper import map_symbols


def git(checkout, *args):
    return subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout


def iso(epoch):
    return datetime.fromtimestamp(int(epoch), timezone.utc).isoformat().replace("+00:00", "Z")


def source_at(checkout, ref, path):
    exists = subprocess.run(["git", "-C", str(checkout), "cat-file", "-e", f"{ref}:{path}"], capture_output=True, timeout=15)
    if exists.returncode:
        return ""
    return git(checkout, "show", f"{ref}:{path}")


def sources_at(checkout, ref):
    paths = git(checkout, "ls-tree", "-r", "--name-only", ref).splitlines()
    return {path: source_at(checkout, ref, path) for path in paths if path.endswith(".py") and not path.startswith(("tests/", "docs/", "examples/"))}


def ensure_checkout(repo, path):
    path = Path(path)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", f"https://github.com/{repo}.git", str(path)], check=True)
    remote = git(path, "remote", "get-url", "origin").strip().removesuffix(".git")
    if remote != f"https://github.com/{repo}":
        raise ValueError("Checkout belongs to another repository")
    return path


def ingest_history(graph, repo, checkout, ref="HEAD", max_commits=None, commit_shas=None):
    commits = commit_shas if commit_shas is not None else git(checkout, "rev-list", "--reverse", "--topo-order", ref).splitlines()
    if max_commits:
        commits = commits[-max_commits:]
    for index, sha in enumerate(commits):
        metadata = git(checkout, "show", "-s", "--format=%H%x00%an%x00%ae%x00%ct%x00%B", sha).split("\0", 4)
        _, author, email, epoch, message = metadata
        timestamp = iso(epoch)
        url = f"https://github.com/{repo}/commit/{sha}"
        graph.nodes("Commit", [{"id": sha, "sha": sha, "message": message.strip(), "author": author, "author_email": email, "timestamp": timestamp, "url": url}])
        person = "git:" + email
        graph.nodes("Person", [{"id": person, "name": author, "login": "", "email": email}])
        provenance = {"source_url": url, "source_type": "git_commit", "timestamp": timestamp, "confidence": 1.0}
        graph.edges("Person", "AUTHORED", "Commit", [edge(person, sha, sha, **provenance)])
        parent_line = git(checkout, "rev-list", "--parents", "-n", "1", sha).split()
        # A merge diff against its first parent is the integration change.
        parent = parent_line[1] if len(parent_line) > 1 else None
        entries = git(checkout, "diff-tree", "--root", "--no-commit-id", "-r", "-M", "--name-status", *( [parent, sha] if parent else [sha])).splitlines()
        for entry in entries:
            fields = entry.split("\t")
            status, new_path = fields[0], fields[-1]
            old_path = fields[1]
            if not new_path.endswith(".py") or new_path.startswith(("tests/", "docs/", "examples/")):
                continue
            before = source_at(checkout, parent, old_path) if parent else ""
            after = source_at(checkout, sha, new_path)
            old = parse_sources(repo, {old_path: before}, sha).symbols if before else []
            new = parse_sources(repo, {new_path: after}, sha).symbols if after else []
            graph.nodes("File", [{"id": f"{repo}:{new_path}", "path": new_path, "language": "python"}])
            graph.edges("Commit", "MODIFIED", "File", [edge(sha, f"{repo}:{new_path}", sha, old_path=old_path, status=status, **provenance)])
            diff = git(checkout, "diff", "--unified=0", "--no-ext-diff", parent, sha, "--", old_path, new_path) if parent else git(checkout, "show", "--format=", "--unified=0", sha, "--", new_path)
            mapped = map_symbols(diff, old, new)
            # Historical identity nodes stay available; current snapshot properties are set last.
            graph.nodes("Symbol", [dict(m["symbol"], last_modified=timestamp) for m in mapped])
            graph.edges("Commit", "MODIFIED_SYMBOL", "Symbol", [edge(sha, m["symbol"]["id"], sha, lines_added=m["lines_added"], lines_deleted=m["lines_deleted"], **provenance) for m in mapped])
        if index % 100 == 0:
            print(f"git_history {index+1}/{len(commits)}", flush=True)
    return len(commits)
