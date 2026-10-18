"""Read-only ingestion, cached raw responses are transport artifacts, not agent context."""
import hashlib
import json
import re
import time
import subprocess
from pathlib import Path
import httpx
from backend.config import ROOT, settings
from backend.graph.client import edge

CLOSING = re.compile(r"\b(?:fix(?:es|ed)?|clos(?:e|es|ed)|resolv(?:e|es|ed))\s+(?:https://github\.com/([\w.-]+/[\w.-]+)/issues/|(?![\w.-]+/[\w.-]+)#)(\d+)", re.I)


def closing_issues(text, repo=None):
    return sorted({int(number) for target, number in CLOSING.findall(text or "") if not target or target == repo})


class GitHub:
    def __init__(self, repo=None, refresh=False):
        self.refresh = refresh
        self.repo = repo or settings.repo
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", self.repo):
            raise ValueError("Expected owner/repository")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if settings.github_token:
            headers["Authorization"] = "Bearer " + settings.github_token
        self.client = httpx.Client(base_url="https://api.github.com", headers=headers, timeout=40)
        self.cache = ROOT / ".data/github" / self.repo.replace("/", "_")
        self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, route, params=None, refresh=False):
        key = hashlib.sha256(json.dumps([route, params], sort_keys=True).encode()).hexdigest()
        file = self.cache / (key + ".json")
        if file.exists() and not (refresh or self.refresh):
            return json.loads(file.read_text())
        for attempt in range(3):
            response = self.client.get(route, params=params)
            if response.status_code in (502, 503, 504) and attempt < 2:
                time.sleep(1 + attempt)
                continue
            response.raise_for_status()
            data = response.json()
            file.write_text(json.dumps(data))
            return data

    def pages(self, route, params=None):
        output = []
        for page in range(1, 101):
            data = self.get(route, {**(params or {}), "per_page": 100, "page": page})
            output.extend(data)
            if len(data) < 100:
                return output
        raise RuntimeError("Pagination exceeds safe limit")

    def issue(self, number, refresh=False):
        data = self.get(f"/repos/{self.repo}/issues/{int(number)}", refresh=refresh)
        if "pull_request" in data:
            raise ValueError("Expected an issue, received a PR")
        return data

    def fix_prs(self, limit=25, recent=False):
        # GitHub search verifies merged state; the search result supplies merged_at.
        output = []
        seen = set()
        for term in ("fixes", "closes", "resolves"):
            term_count = 0
            for page in range(1, 4):
                data = self.get("/search/issues", {"q": f"repo:{self.repo} is:pr is:merged {term} in:body", "sort": "updated" if recent else "created", "order": "desc" if recent else "asc", "per_page": 100, "page": page})
                for pr in data["items"]:
                    if pr["number"] not in seen and closing_issues(pr.get("body"), self.repo):
                        seen.add(pr["number"])
                        output.append(pr)
                        term_count += 1
                        if not recent and len(output) >= limit:
                            return output
                        if recent and term_count >= limit:
                            break
                if len(data["items"]) < 100 or (recent and term_count >= limit):
                    break
        if recent:
            # Sample each closing keyword before the global bound so a newly
            # merged "closes" PR is not crowded out by the "fixes" search.
            output.sort(key=lambda pr: (pr.get("updated_at", pr["created_at"]), pr["number"]), reverse=True)
        return output[:limit]


def item(repo, data, label):
    return {"id": f"{repo}:{label.lower()}:{data['number']}", "github_id": data["id"], "number": data["number"], "title": data["title"], "body": data.get("body") or "", "state": data["state"], "created_at": data["created_at"], "closed_at": data.get("closed_at"), "url": data["html_url"], "author": (data.get("user") or {}).get("login", "unknown"), "updated_at": data.get("updated_at", data["created_at"])}


def ingest_github(graph, repo, limit=25, comments=False, checkout=None, refresh=False, recent=False):
    api = GitHub(repo, refresh=refresh)
    pulls = api.fix_prs(limit, recent=recent)
    report = []
    for pr in pulls:
        number = pr["number"]
        merged_at = pr.get("pull_request", {}).get("merged_at")
        if not merged_at:
            detail = api.get(f"/repos/{repo}/pulls/{number}")
            merged_at = detail.get("merged_at")
        if not merged_at:
            continue
        p = dict(item(repo, pr, "PullRequest"), merged_at=merged_at)
        graph.nodes("PullRequest", [p])
        graph.nodes("Person", [{"id": p["author"], "login": p["author"], "name": p["author"]}])
        prov = {"source_url": p["url"], "source_type": "github_pr", "timestamp": merged_at, "confidence": 1.0}
        graph.edges("Person", "OPENED", "PullRequest", [edge(p["author"], p["id"], p["id"], **dict(prov, timestamp=p["created_at"]))])
        commits = api.pages(f"/repos/{repo}/pulls/{number}/commits")
        missing = [c["sha"] for c in commits if not graph.query("MATCH (c:Commit {id:$sha}) RETURN c.id", {"sha": c["sha"]})]
        if missing:
            from backend.ingestion.git_history import ingest_history
            # Squashed/rebased PR commits need not be reachable from the default branch.
            repository_checkout = checkout or (ROOT / ".data/repo")
            subprocess.run(["git", "-C", str(repository_checkout), "fetch", "origin", f"refs/pull/{number}/head"], check=True, timeout=90, capture_output=True)
            ingest_history(graph, repo, repository_checkout, commit_shas=missing)
        commit_ids = []
        for c in commits:
            sha = c["sha"]
            exists = graph.query("MATCH (c:Commit {id: $sha}) RETURN c.id", {"sha": sha})
            if not exists:
                raise RuntimeError(f"PR #{number} commit {sha} absent from checkout history; fetch the full repository")
            commit_ids.append(sha)
            graph.edges("PullRequest", "CONTAINS_COMMIT", "Commit", [edge(p["id"], sha, p["id"], **prov)])
            login = (c.get("author") or {}).get("login")
            if login:
                graph.nodes("Person", [{"id": login, "login": login, "name": c["commit"]["author"]["name"]}])
                graph.query("MATCH (person:Person)-[:AUTHORED]->(c:Commit {id:$sha}) WHERE person.email=$email SET person.login=$login", {"sha": sha, "email": c["commit"]["author"]["email"], "login": login})
                graph.edges("Person", "AUTHORED", "Commit", [edge(login, sha, "github:" + sha, **dict(prov, timestamp=c["commit"]["committer"]["date"]))])
        linked = []
        for issue_no in closing_issues(p["body"], repo):
            issue = api.get(f"/repos/{repo}/issues/{issue_no}")
            if "pull_request" in issue:
                print(f"skip closing reference #{issue_no}: target is a PR, not an issue", flush=True)
                continue
            i = item(repo, issue, "Issue")
            graph.nodes("Issue", [i])
            graph.nodes("Person", [{"id": i["author"], "login": i["author"], "name": i["author"]}])
            graph.edges("Person", "OPENED", "Issue", [edge(i["author"], i["id"], i["id"], source_url=i["url"], source_type="github_issue", timestamp=i["created_at"], confidence=1.0)])
            graph.edges("PullRequest", "CLOSES", "Issue", [edge(p["id"], i["id"], p["id"], **dict(prov, resolution="closing_keyword"))])
            linked.append(issue_no)
        if comments:
            # Source records live on their parent nodes, each preserving its own timestamp.
            records = api.pages(f"/repos/{repo}/issues/{number}/comments")
            reviews = api.pages(f"/repos/{repo}/pulls/{number}/reviews")
            graph.query("MATCH (p:PullRequest {id:$id}) SET p.comments_json=$comments", {"id": p["id"], "comments": json.dumps(records + reviews)})
            for review in reviews:
                person = (review.get("user") or {}).get("login")
                if person and review.get("submitted_at"):
                    graph.nodes("Person", [{"id": person, "login": person, "name": person}])
                    graph.edges("Person", "REVIEWED", "PullRequest", [edge(person, p["id"], str(review["id"]), source_url=review["html_url"], source_type="github_review", timestamp=review["submitted_at"], confidence=1.0)])
            for issue_no in linked:
                records = api.pages(f"/repos/{repo}/issues/{issue_no}/comments")
                graph.query("MATCH (i:Issue {number:$number}) SET i.comments_json=$comments", {"number": issue_no, "comments": json.dumps(records)})
        report.append({"pr": number, "issues": linked, "commits": commit_ids, "merged_at": merged_at})
        print(f"github PR #{number} -> issues {linked} -> {len(commits)} commits", flush=True)
    return report
