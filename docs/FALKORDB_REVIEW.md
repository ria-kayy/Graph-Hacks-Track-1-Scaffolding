# FalkorDB implementation and hackathon resource review

Reviewed on 4 October 2026 against the [WeMakeDevs resource page](https://www.wemakedevs.org/hackathons/falkordb/resources), the linked official documentation, and this repository. This is an implementation review, not a claim that all example integrations or videos were executed.

## Where FalkorDB determines the result

| Area | Repository implementation | Assessment |
| --- | --- | --- |
| Persistence | `backend/graph/client.py` uses the official Python client; values are passed as parameters and graph labels/relations are allowlisted | FalkorDB is the runtime fact store, not a decorative export |
| Ingestion | AST structure, Git diff overlap, deterministic GitHub closing links, archive opening text, and source-backed claims become graph facts | Keep provenance and revision metadata when expanding the corpus |
| Semantic retrieval | `backend/graph/vectors.py` creates HNSW vector indexes and searches `Issue.embedding` inside FalkorDB | A local embedding model computes vectors; an external vector database is not used |
| Localization | `cypher/localization.cypher` traverses issue -> PR -> commit -> symbol; ranking expands calls and same-file symbols | Graph paths select the functions subsequently inspected |
| Historical validity | `backend/graph/snapshots.py` tags structural edges with actual Git refs; cutoff queries filter evidence timestamps | Snapshot reconstruction is essential; optimizing retrieval must preserve it |
| Impact and reviewers | `cypher/impact.cypher` traverses reverse calls to depth three; expertise combines authorship, fixes and reviews | Zero static callers does not prove zero runtime impact |
| Reviewed actions | `TriagePreview` stores the original issue and exact response/Markdown with scope and expiry | Posting loads the saved preview; no second recommendation is generated |

The new preview records contain no credentials and are not searched as issues or claims. They expire after 30 minutes; expiry is checked on posting, and old preview records are removed when another numbered preview is created. Browser sessions, HTTP workers and MCP processes can retrieve the same preview from the same graph. This remains a local single-user app; preview IDs are not a multi-user authorization system.

## Findings from the resources

### Installation, Docker and Python client

The [getting-started guide](https://docs.falkordb.com/getting-started/) and [Python client](https://github.com/FalkorDB/falkordb-py) match the application's `FalkorDB(...).select_graph(...).query(...)` approach. The [Docker guide](https://docs.falkordb.com/operations/docker) describes persistent volumes, authentication, startup health checks and production settings. The repository already binds its ports to loopback and mounts `/data`. Follow-up testing used the existing Docker container successfully.

Next deployment work: pin the tested image digest, add a database health check, verify persistence after a controlled restart, and select durability settings explicitly. Keep credential configuration outside source control. These deployment changes were reviewed but are outside this patch.

### Cypher, indexing and query plans

The [Cypher reference](https://docs.falkordb.com/cypher/) supports the pattern-based traversal underlying history, localization and impact. The [vector-index documentation](https://docs.falkordb.com/cypher/indexing/vector-index) describes dimensions, HNSW configuration and vector query procedures. The repository computes index dimension from its embedding model and uses parameterized queries.

A documentation example orders cosine `score` descending, while the tested Docker runtime returns zero for identical vectors and the repository treats it as distance. Retain ascending order and `1-distance` conversion, backed by the live identical-vector test and the [procedure source](https://github.com/FalkorDB/FalkorDB/blob/master/src/procedures/proc_vector_query.c); do not change score direction based only on an example. Pinning the runtime and retaining that test protect this behavior.

The current retrieval requests the whole small issue corpus before timestamp filtering. That avoids future neighbors crowding eligible historical results, but scales poorly. Before changing it, measure query plans/latency and test a strategy that preserves historical recall. Profile repeated per-symbol lookups and batch them where equivalent; do not sacrifice temporal correctness for fewer queries.

### Browser and graph algorithms

The [FalkorDB Browser](https://docs.falkordb.com/browser/) can inspect stored graph paths independently of the React interface. Use it to verify actual `CLOSES`, `CONTAINS_COMMIT` and `MODIFIED_SYMBOL` relationships during preparation. The app uses Cytoscape to show a small, selected evidence graph, not the entire database.

The [algorithm catalog](https://docs.falkordb.com/algorithms/) offers pathfinding, centrality and community analysis. Our next experiment should be a bounded, snapshot-aware call-neighborhood feature or expanded impact paths, measured against the current baseline. Adding global PageRank without an evidence-backed improvement would not solve the sparse historical fix corpus.

### GraphRAG SDK, integrations and examples

The linked [GraphRAG SDK](https://github.com/FalkorDB/GraphRAG-SDK) provides document ingestion and incremental-update patterns. Its document lifecycle is useful inspiration for re-ingesting changed repository files. WhyGraph currently needs deterministic AST/Git relationships and temporal provenance, so adopting the SDK would require an evaluation of those invariants rather than replacing the existing pipeline wholesale.

The [integrations](https://docs.falkordb.com/integration/) and [community projects](https://www.falkordb.com/community-projects/) provide examples for later editor/agent and data-pipeline work. They are references, not dependencies installed in this patch. Cloud deployment would require a separate connection/security review; no Cloud account was provisioned.

The resource page also links Cypher, algorithm, Graph/RAG and Cloud videos. Several video pages were inaccessible to the web reader, and the playlist provided no usable transcript. No video-specific conclusions are claimed; the corresponding official documentation above was used instead.

## Validation and remaining work

This patch's acceptance checks are documented in the README: 46 Python tests with Docker, 14 Chromium browser tests, MCP handshake/history query, and the production build. Browser APIs and GitHub navigation/posting are mocked; live database tests use isolated graph names and remove them. No real GitHub comment was posted, no LLM request was made, and the measured evaluation artifacts were not regenerated.

The saved evaluation still shows a graph/vector tie at 30% Top-1. The graph's demonstrated contribution is provenance, historical reconstruction, impact and reviewer routing. Next milestones: broaden prior fix coverage in a separate graph, retain original issue text, reserve a held-out evaluation set, compare expansion on/off, and report ranking errors and latency alongside accuracy.

Sequential retries of one saved preview reuse the exact duplicate marker. Two simultaneous posts can still race between GitHub comment inspection and creation; stronger cross-worker action coordination is future work. There is also an unavoidable interval between checking an issue and submitting a comment; GitHub does not provide an atomic compare-and-post operation in this flow. Live posting needs credentialed validation on an owned fork before presenting it as verified.
