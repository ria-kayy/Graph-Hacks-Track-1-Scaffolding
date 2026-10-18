# Repository investigation implementation and verification

Implemented on PR #1 (`mahima/repo-investigation`), extending its repository ingestion and chat implementation. The React/Cytoscape layout and existing historical benchmark artifacts are retained.

## Changes

- `backend/repositories.py`: isolated identities/checkouts/graphs, atomic registry updates, persistent last-job status, restart interruption reporting, duplicate-job protection, eight outstanding jobs and two workers, actual fetch/reset refresh, current metadata restoration after history ingestion, rationale stage, visible partial failures. Incomplete repositories cannot be queried.
- `backend/agent/evidence.py` (new): typed citations, Git-blob reads at resolved revisions, escaped source URLs, line-span validation, repository/snapshot/symbol checks, commit verification, and exact rationale-source validation.
- `backend/agent/investigation.py`: graph-side lexical scoring across the full snapshot with compact result transfer, bounded source reads for final candidates, full indexed source lexical retrieval, optional current symbol vectors, source-only candidates, retained follow-up topics, canonical evidence verification, correct issue-result decoding, time-filtered historical links, and current methods preferred over large containing classes.
- `backend/agent/toolbox.py` and `planner.py` (new): Pydantic tool schemas and an optional model-selected read-only tool loop. At most four tool calls/four model rounds; 12-second provider timeouts and a 45-second round-start deadline. Invalid arguments, invented citations, model-supplied URLs, provider errors and budget exhaustion preserve retrieval-only output. Tools cannot change repositories, supply Cypher, execute shell commands, or post comments.
- `backend/graph/snapshots.py`: historical file membership for revision-scoped source reads.
- `backend/graph/client.py`: shared database runtime, graph isolation, connection/query timeouts. Sharing the embedded runtime prevents repeatedly starting a FalkorDBLite lifecycle during a single investigation.
- `backend/ingestion/code_parser.py`, `git_history.py`, `github.py`: indexed file text and snapshot-specific search fields (with a one-time migration for existing graphs), bounded Git subprocesses, cache-bypassing refresh and recent-fix selection.
- `backend/tools/localize.py`: independent direct source search in both current and explicit historical snapshots, topical relevance checks before historical projection, visible ranking signals. Original `rank` and evaluation baseline remain available unchanged.
- `backend/tools/history.py` and `cypher/history.cypher`: temporal relationship filtering; a PR-level rationale no longer automatically explains every symbol modified in that PR. Quotes must still exist in attributed stored sources.
- `backend/api/routes.py`, `backend/mcp_server.py`, `backend/main.py`: shared `/api/tools` dispatch, repository-scoped original MCP tools, four additional source/call-context MCP tools, and HTTP administration/posting protected by configurable Bearer credentials, with direct-loopback access retained for the local demo. `WHYGRAPH_PUBLIC=true` disables those HTTP actions even through a local reverse proxy. Custom-repository numbered triage/posting remains disabled.
- `frontend/src/main.jsx`: refresh/recovery controls, ingestion errors, correct selected-repository identity/counts, guarded polling, and protection against stale chat responses restoring another repository's conversation. Styling and graph visualization are retained.
- Tests: new `test_agent_tools.py`, `test_repository_workflows.py`, `test_investigation_integration.py`; updates to API, investigation, MCP, ranking, triage and Playwright regressions. `scripts/check_mcp.py` now checks source search and investigation as well as discovery and commit search.

## Run from a fresh clone

```bash
cp .env.example .env
# Set FALKORDB_MODE=lite in .env, or use the existing Docker configuration.
uv sync --locked --extra dev --extra mcp --extra lite
uv run python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Use **Add and index** with `https://github.com/pallets/click`. Wait for completion, select that repository, and ask a natural-language question under **Investigate**. This workflow does not require the legacy demo ingestion commands. Optional `semantic` dependencies enable embeddings; `LLM_API_KEY`, `LLM_MODEL`, and optional `LLM_BASE_URL` enable the Responses-compatible provider tool loop. No model name or credential is committed.

HTTP example:

```json
POST /api/chat
{"repo_id":"<repository_id>","query":"Where is retry implemented?"}
```

Pass the returned `conversation_id` for follow-ups. Supplying `as_of` explicitly reconstructs the historical source and filters later evidence. Current queries use the indexed revision regardless of issue creation date. Tool calls share `POST /api/tools` with `{repo_id, tool, arguments, as_of}`. MCP retains the original six names, adds source search/commit search/investigate, and adds read_source/get_symbol_context/trace_callers/trace_callees.

Use one backend process for local ingestion. Jobs and repository metadata persist, but conversation state is bounded in-process memory and resets on restart. Restarted unfinished jobs become recoverable failures; use Refresh to retry. Managed checkouts are application-owned and refresh resets them to fetched origin/HEAD.

## Actual verification

- `WHYGRAPH_INTEGRATION=1 ... python -m pytest -q`: **92 passed**, using actual FalkorDBLite and real Git fixture histories. One upstream Starlette/httpx deprecation warning.
- `npm run build`: passed; existing large-bundle warning remains.
- `npm run test:e2e`: **18 passed** in Chromium. These browser tests intercept HTTP responses; they are not a live ingestion browser test.
- `python -m scripts.check_mcp`: real stdio handshake, **13 tools**, repository-scoped search_commits, search_code and investigate all passed against the live Click graph.
- Live public Click ingestion: **747 symbol nodes, 549 commits, 25 PRs, 25 issues**. Indexed revision `2247b35ea1c47c727d7a06e51fa280e12a863ff6`. Symbols include historical identities; this is not a current-function count. Embeddings unavailable (`sentence_transformers` not installed), reported as ready_with_warnings.
- Real HTTP registration of the indexed repository and `/api/chat`: HTTP 200, retrieval_only, verified source and historical graph links. No GitHub write or paid model request was made.
- Fixture refresh confirms a fetch operation, revision advance, changed source retrieval, and removal of old code from current search. Its upstream fetch is simulated; actual parsing, Git reset/history and graph updates are real.

## Example real output

Question: “The progress bar does not update after each item is processed. Where should I investigate?”

The API ranked `click._termui_impl.ProgressBar.generator` first. Its implementation is verified at [the indexed source, lines 349–380](https://github.com/pallets/click/blob/2247b35ea1c47c727d7a06e51fa280e12a863ff6/src/click/_termui_impl.py#L349-L380). `ProgressBar.update` is another retrieved candidate. The response explicitly says these are investigation starting points and that no runtime failure or root cause has been reproduced.

A separate historical commit-message match is [8780a763](https://github.com/pallets/click/commit/8780a763aab11f69258acccbcb9d0d97e92ebadb), with graph-verified links to [PR #706](https://github.com/pallets/click/pull/706) and [issue #651](https://github.com/pallets/click/issues/651). The response labels it historical background, not a diagnosis. The bounded history does not establish the entire file-move lineage to the current symbol, so this path is not presented as direct causal evidence for today's problem.

## Limits and unverified behavior

- Python AST support only. Dynamic calls and arbitrary/multiple symbol renames remain approximate. Lexical search ranks the full eligible symbol set within FalkorDB and returns at most 30 compact candidate records (for up to 10 final results); database scan cost still grows with repository size. File ingestion caps remain 5,000 Python files, 2 MB per file and 100 MB total. Historical Git parsing and remote clone size are not a strict aggregate disk quota.
- Managed ingestion retains 500 mainline commits and enriches up to 25 recently updated merged closing PRs per run, sampling all three closing keywords before limiting. Refresh bypasses all related GitHub transport caches; the legacy CLI defaults to its original oldest-first corpus. GitHub rate-limit/enrichment failures become visible warnings; they can reduce historical coverage. Public GitHub rename/transfer canonicalization is not implemented; identity normalization is syntactic.
- Embedding generation and a real credentialed LLM were not exercised. Model routing/schema/budget/citation failures are tested with provider fixtures. Historical source search deliberately skips mutable current symbol vectors to avoid future text leakage.
- The model loop uses the existing lightweight Python workflow instead of adding LangGraph. Provider round time is bounded, but slow graph/tool calls have separate query/subprocess timeouts; the complete turn has no hard wall-clock cancellation.
- Last-job persistence and ingestion deduplication assume one local API process. There is no distributed queue or cross-process registry lock. Conversations are not durable or shared between HTTP/MCP processes.
- The original 20-issue benchmark artifacts were preserved and not regenerated: the live graph lacks its original issue embeddings/opening-event setup. No accuracy improvement is claimed. New tests assert isolation, source validity and rejection behavior; they are not a measured localization benchmark or held-out accuracy evaluation.
- Docker/server deployment and a complete live browser-to-GitHub ingestion run were not exercised here. GitHub posting safeguards remain covered with mocked transport, with no real comment posted. UI custom-repository triage remains disabled; use repository chat/localize or read-only MCP triage.


## Follow-up to the review of c2d5f1e

| Finding | Implemented correction | Regression evidence |
| --- | --- | --- |
| 5,000-symbol cutoff | Graph-side scoring sees every symbol in the selected snapshot; the limit applies after ranking | A real FalkorDB fixture with 5,002 symbols in one file retrieves its last symbol using a unique body token beyond the 1,200-character summary |
| Stale GitHub metadata / oldest-first window | Refresh bypasses caches for all GitHub reads; managed ingestion selects recently updated merged fixes across all three keywords | Cached initial search followed by a newly merged fixture PR produces a new issue → PR → commit path during a real graph refresh; the original CLI selection remains oldest-first |
| Repeated full files | Return compact snapshot symbol metadata and scores; read Git blobs only for final candidates, caching each file within the search | Large-file regression transfers less than 2 KB of candidate rows and performs one source read |
| Inflated symbol counts | `counts.Symbol` counts DISTINCT symbols at `indexed_ref`; `graph_counts.Symbol` preserves the total | Refresh removes old functions from current counts while retaining history; `/api/status` agrees |
| Proxy administration | `WHYGRAPH_ADMIN_TOKEN` requires constant-time Bearer verification regardless of peer; without it, forwarded/nonlocal Host/Origin requests fail. Public mode disables all HTTP admin actions | Proxy-header/host/origin denial tests, valid/invalid token tests, and browser token forwarding test |

The live Click refresh fetched origin and retained revision `2247b35ea1c47c727d7a06e51fa280e12a863ff6` (upstream had not advanced). It added verified paths for PR #3858 → issue #3822 → commit `22177f857a34e3c35ba957553853a37f23feb37e`, PR #3820 → issue #1054 → commit `bb86cdea6e83bc8e2711290eeffb4c8654baa7a3`, and PR #3819 → issue #3135 → commit `c4597ed340477f3a69cfb8a9944149fab9d09b74`. GitHub then returned HTTP 403 for its unauthenticated rate limit. The job completed as `ready_with_warnings`, explicitly identifying incomplete GitHub enrichment and unavailable embeddings. It did not silently reuse stale cache data.

After refresh: **630 current symbols / 747 total symbol nodes, 549 commits, 29 PR nodes, 28 issue nodes**. A PR node may exist before a partially failed enrichment completes its issue links. The progress-bar question still ranks `ProgressBar.generator` first with the same revision-pinned source citation. Real MCP handshake, 13-tool discovery, commit search, source search and investigation passed on the refreshed graph; the check asserts nonempty source evidence and matching repository/revision fields.

A GitHub Actions workflow now runs Python tests with a FalkorDB service, the frontend build, and Playwright. Its remote result is separate from the local validation above. The actual public deployment proxy has not been supplied or tested. Configure either the admin token (for authenticated administration) or `WHYGRAPH_PUBLIC=true` (read-only), rather than relying on proxy network origin.
