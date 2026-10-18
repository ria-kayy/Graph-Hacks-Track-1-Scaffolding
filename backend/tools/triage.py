import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from backend.config import settings
from backend.graph.client import properties
from backend.ingestion.github import GitHub
from backend.agent.workflow import analyze
from backend.tools.common import cutoff, now

PREVIEW_LIFETIME = timedelta(minutes=30)


def save_preview(graph, issue, result):
    """Persist the exact reviewed response in the same FalkorDB graph."""
    created = now()
    expires = (datetime.fromisoformat(created.replace("Z", "+00:00")) + PREVIEW_LIFETIME).isoformat().replace("+00:00", "Z")
    result["preview_id"] = uuid.uuid4().hex
    result["preview_expires_at"] = expires
    graph.query("MATCH (p:TriagePreview) WHERE p.expires_at <= $at DELETE p", {"at": created})
    graph.nodes("TriagePreview", [{
        "id": result["preview_id"], "repo": settings.repo,
        "issue_repo": settings.triage_fork or settings.repo,
        "issue_number": issue["number"], "created_at": created, "expires_at": expires,
        "issue_json": json.dumps(issue), "result_json": json.dumps(result),
    }])


def post_preview(graph, issue_number, preview_id, as_of):
    if not isinstance(issue_number, int) or issue_number < 1 or not preview_id:
        raise ValueError("Posting requires an existing fork issue and its preview_id. Generate a preview first.")
    rows = graph.query("MATCH (p:TriagePreview {id:$id}) RETURN p", {"id": preview_id})
    if not rows:
        raise ValueError("Preview not found or expired. Generate a fresh preview.")
    preview = properties(rows[0][0])
    if datetime.fromisoformat(preview["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise ValueError("Preview expired. Generate a fresh preview.")
    if (preview["repo"] != settings.repo or preview["issue_repo"] != settings.triage_fork
            or preview["issue_number"] != issue_number):
        raise ValueError("Preview does not match this fork and issue. Generate a fresh preview.")
    result = json.loads(preview["result_json"])
    if as_of and cutoff(as_of) != result["localization"]["as_of"]:
        raise ValueError("Historical cutoff changed since preview. Generate a fresh preview.")
    # Do not fetch new analysis or regenerate Markdown: post exactly what was reviewed.
    result["action"] = post_comment(json.loads(preview["issue_json"]), result["markdown"])
    return result


def render(result):
    local = result["localization"]
    lines = ["## WhyGraph Triage", "", "### Likely affected functions", ""]
    for index, candidate in enumerate(local["candidates"], 1):
        lines.append(f"{index}. `{candidate['symbol']['qualified_name']}` — ranking score {candidate['score']:.3f}")
        direct = candidate.get("direct_evidence")
        if direct:
            lines.append(f"   - Current source: [{direct['file_path']}:{direct['start_line']}-{direct['end_line']}]({direct['source_url']}) (direct code match; investigation starting point)")
    if not local["candidates"]:
        lines.append("No supported function candidates were found before the issue cutoff. More historical evidence is needed.")
    lines += ["", "### Evidence paths", ""]
    for finding in result["findings"]:
        candidate = finding["candidate"]
        lines.append(f"**`{candidate['symbol']['qualified_name']}`**")
        for path in candidate["paths"][:3]:
            lines.append(f"- [Issue #{path['issue']['number']}]({path['issue']['url']}) → [PR #{path['pr']['number']}]({path['pr']['url']}) → [commit {path['commit']['sha'][:8]}]({path['commit']['url']}) → `{path['modified_symbol']}`" + (f" → {path['expansion']} → `{path['candidate']}`" if path["expansion"] else ""))
            if path.get("relocation_source"):
                lines.append(f"  - File relocation verified by [Git rename]({path['relocation_source']}).")
        lines += ["", "Historical rationale:"]
        claims = finding["history"]["claims"][:3]
        for claim in claims:
            if claim.get("claim_type") == "derived":
                lines.append(f"- Derived interpretation: {claim['text']} ([support]({claim['source_url']}))")
            else:
                lines.append("\n".join("> " + line for line in claim["source_span"].splitlines()))
                lines.append(f"[Source]({claim['source_url']}) · confidence {claim['confidence']:.2f}")
        if not claims:
            lines.append("No verified rationale available for this path.")
        lines += ["", "Blast radius (callers → selected function):"]
        for caller in finding["impact"]["transitive_callers"][:5]:
            lines.append("- " + " → ".join(f"`{name}`" for name in caller["path"]))
        if not finding["impact"]["transitive_callers"]:
            lines.append("No statically resolved callers found.")
        lines += ["", "Suggested reviewers:"]
        for person in finding["experts"]["experts"][:2]:
            urls = person["sources"]
            source = f" ([evidence]({urls[0]}))" if urls else ""
            lines.append(f"- @{person['login']}: {person['direct_changes']} symbol changes, {person['fix_count']} related fixes, {person['review_count']} reviews{source}")
        if not finding["experts"]["experts"]:
            lines.append("Insufficient verified person evidence.")
        lines.append("")
    lines += ["### Confidence", "", local["confidence"].capitalize() + ". Scores are ranking signals, not calibrated probabilities.", f"Evidence cutoff: {local['as_of']}. Source snapshot: `{local['snapshot_ref']}`.", "", "### Agent trace", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(result["trace"], 1)]
    body = "\n".join(lines)
    return body + "\n\n<!-- whygraph:" + hashlib.sha256(body.encode()).hexdigest()[:20] + " -->"


def post_comment(issue, body):
    if not settings.triage_fork or settings.triage_fork == settings.repo:
        raise ValueError("Set TRIAGE_FORK to your fork; upstream posting is disabled")
    if not settings.github_token:
        raise ValueError("GITHUB_TOKEN is required to post")
    api = GitHub(settings.triage_fork)
    fork = api.get(f"/repos/{settings.triage_fork}", refresh=True)
    user = api.get("/user", refresh=True)
    if not fork.get("fork") or fork.get("parent", {}).get("full_name", "").lower() != settings.repo.lower():
        raise ValueError("TRIAGE_FORK must be a verified fork of TARGET_REPO")
    if fork["owner"]["login"].lower() != user["login"].lower():
        raise ValueError("Posting is restricted to the authenticated user's own fork")
    number = int(issue["number"])
    current = api.get(f"/repos/{settings.triage_fork}/issues/{number}", refresh=True)
    if "pull_request" in current:
        raise ValueError("Triage comments are only supported on issues")
    if current["title"] != issue["title"] or (current.get("body") or "") != issue.get("body", ""):
        raise ValueError("Fork issue changed since preview; generate a fresh preview")
    marker = body.rsplit("<!-- whygraph:", 1)[-1]
    # Read fresh comments for duplicate prevention; no mutation until explicit post=true.
    for page in range(1, 101):
        response = api.client.get(f"/repos/{settings.triage_fork}/issues/{number}/comments", params={"per_page": 100, "page": page})
        response.raise_for_status()
        comments = response.json()
        for comment in comments:
            if marker in comment.get("body", ""):
                return {"url": comment["html_url"], "already_posted": True}
        if len(comments) < 100:
            break
    else:
        raise RuntimeError("Too many comments to safely check for duplicates")
    response = api.client.post(f"/repos/{settings.triage_fork}/issues/{number}/comments", json={"body": body})
    response.raise_for_status()
    return {"url": response.json()["html_url"], "already_posted": False}


def triage(graph, issue, post=False, as_of=None, preview_id=None):
    if post:
        return post_preview(graph, issue, preview_id, as_of)
    if preview_id:
        raise ValueError("preview_id is only used when posting a saved preview")
    if isinstance(issue, int):
        data = GitHub(settings.triage_fork or settings.repo).issue(issue, refresh=True)
        from backend.ingestion.github import item
        issue = item(settings.triage_fork or settings.repo, data, "Issue")
    result = analyze(graph, issue, as_of=as_of)
    result["markdown"] = render(result)
    result["action"] = {"posted": False, "mode": "preview"}
    if issue.get("number"):
        save_preview(graph, issue, result)
    return result
