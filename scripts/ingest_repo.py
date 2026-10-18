import argparse
import json
from datetime import datetime, timezone
from backend.config import ROOT, settings
from backend.graph.client import Graph
from backend.ingestion.code_parser import parse_sources, persist
from backend.ingestion.git_history import ensure_checkout, git, sources_at, ingest_history
from backend.ingestion.github import ingest_github


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=settings.repo)
    parser.add_argument("--ref", default=settings.ref)
    parser.add_argument("--stage", choices=["code", "git", "github", "all"], default="all")
    parser.add_argument("--prs", type=int, default=25)
    parser.add_argument("--comments", action="store_true")
    args = parser.parse_args()
    if args.repo != settings.repo:
        raise ValueError("Single repository MVP: set TARGET_REPO to match --repo")
    graph = Graph()
    graph.initialize()
    existing = graph.query("MATCH (r:Repository) RETURN r.id")
    if existing and existing != [[args.repo]]:
        raise ValueError("Graph already indexes another repository; choose a fresh FALKORDB_GRAPH")
    checkout = ensure_checkout(args.repo, ROOT / ".data/repo")
    ref = git(checkout, "rev-parse", args.ref).strip()
    graph.nodes("Repository", [{"id": args.repo, "owner": args.repo.split("/")[0], "name": args.repo.split("/")[1], "url": f"https://github.com/{args.repo}", "default_branch": git(checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip().removeprefix("origin/"), "indexed_ref": ref, "indexed_at": datetime.now(timezone.utc).isoformat()}])
    if args.stage in ("git", "all"):
        print("commits ingested", ingest_history(graph, args.repo, checkout, ref), flush=True)
    if args.stage in ("code", "git", "all"):
        parsed = parse_sources(args.repo, sources_at(checkout, ref), ref)
        persist(graph, parsed, args.repo, ref)
        print(json.dumps({"symbols": len(parsed.symbols), "calls": len(parsed.calls), "imports": len(parsed.imports), "warnings": parsed.warnings}), flush=True)
    if args.stage in ("github", "all"):
        report = ingest_github(graph, args.repo, args.prs, args.comments)
        (ROOT / ".data/ingestion-report.json").write_text(json.dumps(report, indent=2))
        print("linked PRs", len(report), flush=True)
    graph.query("MATCH (r:Repository {id:$repo}) SET r.ingestion_stage=$stage", {"repo": args.repo, "stage": args.stage})


if __name__ == "__main__":
    main()
