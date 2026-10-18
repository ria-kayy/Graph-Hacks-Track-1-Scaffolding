import argparse
import json
import sys
from backend.graph.client import Graph
from backend.tools.history import history
from backend.tools.impact import impact
from backend.tools.experts import experts
from backend.tools.similar import similar_issues
from backend.tools.localize import localize
from backend.tools.triage import triage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=["history", "impact", "experts", "similar_issues", "localize", "triage"])
    parser.add_argument("--symbol")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--issue", type=int)
    parser.add_argument("--as-of")
    parser.add_argument("--post", action="store_true", help="Explicitly post to your verified fork")
    parser.add_argument("--preview-id", help="ID returned by the numbered-issue preview; required for --post")
    args = parser.parse_args()
    if args.post and (args.tool != "triage" or args.issue is None):
        parser.error("--post requires triage --issue NUMBER")
    if args.post and not args.preview_id:
        parser.error("--post requires --preview-id from a reviewed preview")
    if args.preview_id and not args.post:
        parser.error("--preview-id requires --post")
    if args.tool in ("history", "impact", "experts") and not args.symbol:
        parser.error("--symbol is required")
    graph = Graph()
    if args.tool in ("history", "impact", "experts"):
        result = {"history": history, "impact": impact, "experts": experts}[args.tool](graph, args.symbol, args.as_of)
    elif args.tool == "similar_issues":
        result = similar_issues(graph, args.title + "\n" + args.body, args.as_of)
    elif args.tool == "localize":
        result = localize(graph, {"title": args.title, "body": args.body}, args.as_of)
    else:
        result = triage(graph, args.issue if args.issue else {"title": args.title, "body": args.body}, args.post, args.as_of, args.preview_id)
        if result.get("preview_id"):
            print(f"Preview ID: {result['preview_id']} (expires {result['preview_expires_at']})", file=sys.stderr)
    print(result["markdown"] if args.tool == "triage" else json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
