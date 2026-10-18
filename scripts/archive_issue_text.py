"""Recover original opening-event text, so later edits cannot contaminate evaluation."""
import gzip
import json
from datetime import datetime
import httpx
from backend.config import ROOT
from backend.graph.client import Graph, properties


def recover(graph):
    cache = ROOT / "evaluation/issue-snapshots.json"
    saved = json.loads(cache.read_text()) if cache.exists() else []
    by_identity = {r["id"]: r for r in saved}
    issues = [properties(r[0]) for r in graph.query("MATCH (i:Issue) RETURN i ORDER BY i.created_at")]
    for issue in issues:
        if issue["id"] in by_identity:
            continue
        date = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
        if date.year < 2015:
            graph.query("MATCH (i:Issue {id:$id}) SET i.original_unavailable_reason='Pre-2015 Timeline API archives do not contain original issue text'", {"id": issue["id"]})
            print(f"skip issue #{issue['number']}: pre-2015 archive has no original text", flush=True)
            continue
        hour = date.strftime("%Y-%m-%d-") + str(date.hour)
        url = f"https://data.gharchive.org/{hour}.json.gz"
        file = ROOT / ".data" / (hour + ".json.gz")
        print(f"recover original Issue #{issue['number']} from {url}", flush=True)
        if not file.exists():
            temporary = file.with_suffix(".partial")
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as stream:
                    for chunk in response.iter_bytes():
                        stream.write(chunk)
            temporary.rename(file)
        found = None
        with gzip.open(file, "rt") as stream:
            for line in stream:
                event = json.loads(line)
                if event.get("type") != "IssuesEvent" or event.get("payload", {}).get("action") != "opened":
                    continue
                original = event["payload"].get("issue", {})
                if not isinstance(original, dict):
                    continue
                original_id = original.get("id")
                if original_id == issue.get("github_id") and original.get("number") == issue["number"]:
                    if original["created_at"] != issue["created_at"]:
                        raise ValueError("Archive issue creation timestamp mismatch")
                    found = {"id": issue["id"], "github_id": original_id, "number": issue["number"], "title": original["title"], "body": original.get("body") or "", "created_at": original["created_at"], "event_id": event.get("id"), "archive_url": url, "archive_repo": event.get("repo", event.get("repository"))}
                    break
        file.unlink()
        if not found:
            raise RuntimeError(f"Original opening event for issue #{issue['number']} was not found; refusing current edited text")
        by_identity[issue["id"]] = found
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(list(by_identity.values()), indent=2))
    for record in by_identity.values():
        graph.query("MATCH (i:Issue {id:$id}) SET i.original_title=$title,i.original_body=$body,i.original_source_url=$source,i.original_event_id=$event", {"id": record["id"], "title": record["title"], "body": record["body"], "source": record["archive_url"], "event": record["event_id"]})
    print("Verified original issue snapshots:", len(by_identity), flush=True)


if __name__ == "__main__":
    recover(Graph())
