# Track 01 demo: evidence, decisions, and one reviewed action

Use this as a narrated three-minute walkthrough. Record the running application and your voice. Keep the camera on the current step; expand details only when explaining them. Package name: **WhyGraph — FalkorDB repository investigation and triage**. Do not claim affiliation with similarly named projects.

## Before recording

- Start FalkorDB, the backend, and Vite using README instructions. Check `/api/health` and populated `/api/status` counts.
- Configure `LLM_API_KEY`, `LLM_MODEL`, and optionally `LLM_BASE_URL` in local `.env`, then restart the backend. A retrieval-only run does not demonstrate model autonomy.
- Run the investigation once to warm up the embedding model. Confirm **Model execution** says **completed** and includes actual model-selected calls. An answer with zero calls demonstrates synthesis only. Do not rehearse a fixed call order as if the model chose it.
- For the external-action segment, configure your valid GitHub token and owned Click fork, create a disposable test issue there, then restart the backend. Review the numbered issue's exact preview before choosing to post. Posting is a separate user action; the planner has read-only tools.
- Record only a successful live run. Mock-provider and browser-fixture tests verify behavior, but are not evidence of a credentialed model run or a live GitHub post.

## 0:00–0:20 — The problem

“Code shows what runs. The reason a workaround exists can live years away in an issue or pull request. This app connects source to historical fixes in FalkorDB, then uses that connected evidence to investigate a report.”

Show the repository and live counts briefly. Open **Investigate**.

## 0:20–1:20 — Let the model choose

Ask: **“The progress bar seems to advance before work finishes. Find the implementation, check its callers, and look for a historical fix that explains the update order. Distinguish current source from historical background.”**

After completion, show **Model execution**. Explain only the choices actually recorded: the selected tool, its public purpose, arguments, and returned evidence. Explain how the next call responds to the preceding result. Show the stop reason and verified source citations. If the run falls back or ends at a budget, explain that outcome and resolve it before recording the final submission.

The app performs bootstrap retrieval first. The model then chooses optional additional calls; this is bounded model-assisted investigation. Its functions dispatch locally and are also exposed through the separate MCP server. Do not describe local dispatch as a model using an MCP transport.

## 1:20–2:05 — Make the graph earn its place

Open **Issue triage** with the progress-bar report. Show the focused path from issue #651 through PR #706 and its commit to the changed function. Select a node, inspect the highlighted connections, and open the source. Toggle **All returned evidence** to show the additional returned paths.

Expand the top candidate's **Blast radius and reviewers**. Explain that ranking is deterministic here. A related caller is connected by a static call edge; its rank is not proof that it caused the bug. Missing verified rationale must remain missing.

“Semantic similarity finds related text. The graph supplies inspectable fix relationships, callers, and contributor evidence.”

Do not claim an accuracy advantage. To demonstrate a graph-specific localization win, first find and reproduce a real held-out case where vector-only misses and graph traversal recovers the relevant existing function. The checked-in 20-case evaluation currently ties vector-only.

## 2:05–2:40 — Review, then act

Enter the test issue number on your configured fork. Generate its preview, open **GitHub comment preview**, and inspect the Markdown. Explicitly choose **Post triage comment to my fork**, then open **Open posted comment**. Explain that the user approves the exact preview and that graph-backed recommendations inform this action.

If no credentials or test fork are available, show preview only and state that live posting remains unverified. Do not substitute fixture responses or claim an autonomous external action.

## 2:40–3:00 — Honest evaluation

Open **Evaluation**: 20 historical issues; WhyGraph and vector-only tie at 30% Top-1 and 0.300 MRR. Mention original issue text and historical cutoffs, then close with the demonstrated value: inspectable connected evidence, bounded tool choice, and a reviewed action.

## Current verification boundary

The execution record, error/fallback behavior, graph controls, and action guards can be tested locally without paid-model or GitHub-write credentials. A final submission still needs a credentialed model run with nonempty selected-tool steps and a real posted-comment URL to substantiate those two claims. This document is a recording script, not proof that those actions occurred.
