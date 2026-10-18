# Measured evaluation analysis

The 20-case run in `results.json` measures Top-1 of 20% for BM25, 30% for MiniLM retrieval with direct fix projection, and 30% for WhyGraph. The vector and graph approaches also tie on Top-3, Top-5, MRR and Recall@5. This experiment does **not** demonstrate improved localization accuracy from graph expansion.

The six vector/graph Top-1 hits were issues #790, #866, #919, #925, #1047 and #1058. They concern shell completion, where the selected corpus contains several earlier fixes touching overlapping functions. Their historical issue → PR → commit → symbol paths are retained in the case outputs.

Issues #323, #409 and #474 produce no graph predictions at their cutoffs. The available fix corpus has no sufficiently early eligible paths for those source snapshots. They remain failures in the denominator. Other misses arise in a sparse corpus covering unrelated features, where retrieving an older issue cannot supply a relevant prior modified function. Some fix functions were newly introduced or removed by their eventual fixes, while localization can only recommend symbols present before the issue.

Graph expansion can add callers and same-file candidates, but in this run those additions do not add a gold function to the top five. The scoring formula generally keeps directly modified functions ahead of these weaker structural neighbors. Increasing expansion weight based on these twenty outcomes would be test-set tuning, so the weights were left unchanged.

These results are constrained by 28 selected fix PRs from one repository, 20 evaluation issues, approximate static calls, and opening-event text without later valid pre-cutoff comments. Pre-2015 events lack original descriptions and are excluded explicitly for evidence availability. The 26 verified post-2014 original snapshots are saved with archive/event provenance; later GitHub edits are not used as historical issue text.

A useful next evaluation would ingest a broader prior fix corpus, keep a separate held-out set, compare expansion-on/off with unchanged embeddings, and examine per-component ranking errors. The current graph still provides provenance, impact and reviewer routing, but those capabilities should not be presented as evidence of better localization accuracy.
