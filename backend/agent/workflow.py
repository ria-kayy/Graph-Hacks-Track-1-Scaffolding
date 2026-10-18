"""The graph selects which tools run next, with a bounded, visible trace."""
from backend.tools.localize import localize
from backend.tools.impact import impact
from backend.tools.history import history
from backend.tools.experts import experts


def analyze(graph, issue, as_of=None):
    localization = localize(graph, issue, as_of=as_of)
    at = localization["as_of"]
    findings = []
    for candidate in localization["candidates"][:3]:
        identity = candidate["symbol"]["id"]
        findings.append({"candidate": candidate, "history": history(graph, identity, at), "impact": impact(graph, identity, at), "experts": experts(graph, identity, at)})
    return {"issue": {k: issue[k] for k in ("number", "title", "url") if k in issue}, "localization": localization, "findings": findings, "trace": localization["trace"] + [f"history + impact + experts for {len(findings)} graph-selected symbols", "source-backed recommendation preview"]}
