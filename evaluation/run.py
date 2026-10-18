import argparse
import csv
import json
from datetime import datetime, timezone
from backend.config import ROOT, settings
from backend.graph.client import Graph
from backend.graph.snapshots import ensure_snapshot
from backend.graph.vectors import retrieve
from backend.tools.localize import rank
from evaluation.dataset import dataset
from evaluation.baselines import lexical_neighbors, direct_predictions
from evaluation.metrics import metrics, aggregate


def run(graph, size=20):
    cases = dataset(graph, size)
    per_case = []
    for index, case in enumerate(cases):
        issue = case["issue"]
        at = issue["created_at"]
        ref = ensure_snapshot(graph, at)
        text = issue["title"] + "\n" + issue["body"]
        lexical = lexical_neighbors(graph, text, at, issue["id"])
        semantic = retrieve(graph, text, at, exclude=issue["id"])
        predictions = {"keyword": direct_predictions(graph, lexical, at, ref), "vector": direct_predictions(graph, semantic, at, ref), "whygraph": [c["symbol"]["id"] for c in rank(graph, semantic, at, ref)[:5]]}
        # Gold labels are accessed only AFTER all predictions, never passed to retrieval.
        for approach, values in predictions.items():
            per_case.append({"issue": issue["number"], "as_of": at, "snapshot_ref": ref, "approach": approach, "predictions": values, "actual": case["actual"], "eligible_historical_issues": len(semantic), **metrics(values, case["actual"])})
        print(f"eval {index+1}/{len(cases)} issue #{issue['number']}", flush=True)
    summaries = {approach: aggregate([{key: row[key] for key in ("top1", "top3", "top5", "mrr", "recall5")} for row in per_case if row["approach"] == approach]) for approach in predictions}
    return {"repo": settings.repo, "dataset_size": len(cases), "measured_at": datetime.now(timezone.utc).isoformat(), "embedding_model": settings.embedding_model, "methodology": {"query_text": "Verified GH Archive IssuesEvent opened snapshots (original title and body)", "cutoff": "issue.created_at", "historical_text": "original opening snapshots; edited text excluded unless its availability is before cutoff", "structure": "actual Git source snapshot immediately before cutoff", "history": "PR merge time, commits, and all path edge timestamps <= cutoff", "claims": "created_at <= cutoff; no backdated extraction", "ground_truth": "functions/methods modified by merged fix PR commits", "selection": "first 20 chronological closed issues with merged fix PRs and function changes; no performance-based exclusions", "cold_start": "cases with no available historical fixes remain in denominator", "baselines": "BM25 or MiniLM issue retrieval, then direct historical-fix projection without expansion", "limitations": ["Twenty issues from one repository; most preceding fixes are not in the 25-PR corpus", "Best-effort static Python call resolution", "Symbols added by a future fix cannot be predicted as existing code", "HNSW queries request the full MVP issue corpus before time filtering", "Original opening text omits later valid pre-cutoff comments"]}, "summary": summaries, "cases": per_case}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=settings.repo)
    parser.add_argument("--size", type=int, default=20)
    args = parser.parse_args()
    if args.repo != settings.repo:
        raise ValueError("--repo must match TARGET_REPO")
    if args.size < 20:
        raise ValueError("The required evaluation minimum is twenty issues")
    result = run(Graph(), args.size)
    directory = ROOT / "evaluation"
    (directory / "results.json").write_text(json.dumps(result, indent=2))
    with (directory / "results.csv").open("w", newline="") as file:
        fields = list(result["cases"][0])
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in result["cases"]:
            writer.writerow({k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()})
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
