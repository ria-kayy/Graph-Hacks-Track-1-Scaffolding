# Teammate testing message

Hey team — the WhyGraph MVP is ready for testing:
https://github.com/Abhigyan-Shekhar/Graph-Hacks-Brain

It indexes Click's Python code and connects functions to commits, PRs, issues, and source-backed rationale in FalkorDB. You can inspect function history, preview issue triage, follow evidence paths, and see suggested reviewers.

**How to run**

1. Clone the repo and follow the README's fresh-clone setup. You need Python 3.12+, uv, Git, Node 22.12+, and either Docker or FalkorDBLite. Copy `.env.example` to `.env`; use your own GitHub token if ingestion hits public rate limits. No LLM key is needed.
2. Start the database and run the ingestion commands in order. The graph/database and downloaded models are local and aren't included in the repo, so the first setup takes longer.
3. From the repo root, start the backend:
   ```bash
   uv run python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```
4. In a second terminal:
   ```bash
   cd frontend
   npm ci
   npm run dev
   ```
5. Open http://127.0.0.1:5173. Check http://127.0.0.1:8000/api/health if the UI can't connect.

**Please test**

- Function history: `click._termui_impl.ProgressBar.generator` — check the PR #706 / issue #651 evidence and source links.
- Issue triage: “Progress bar does not update after each item is processed.” — inspect functions, graph paths, rationale, reviewer evidence, and trace.
- Edit the issue text after a preview — the old recommendation should clear.
- Evaluation: saved Top-1 scores are keyword 20%, vector 30%, WhyGraph 30%. The graph tied vector retrieval in this 20-issue sample; we aren't claiming an accuracy improvement.
- Run the README's automated checks if you can: pytest, live FalkorDB tests, MCP handshake, and frontend build.

Please leave fork/token posting settings blank for routine testing. Posting requires a separately configured fork issue and an explicit action. Live GitHub posting and optional LLM extraction still need credentialed validation; Docker setup is documented but development validation used FalkorDBLite.

File bugs in this repo with your OS, Python/Node versions, Docker/Lite mode, exact repro steps or command, expected versus actual behavior, and relevant logs/screenshots. Remove credentials from anything you share. Especially useful feedback: fresh setup failures, confusing evidence, wrong function recommendations, broken graph interactions, or missing source links.
