# September 12, 2026 results

Exact copies of the website result files from sanka-public revision
`0a127a85606c46cba2fdb16218e27015b5fd9d76` under `public/bench/`.
Live download verification returned HTTP 403 during preparation; these are
verified against committed website source, not a claim about the live deployment.

- `latest-2026-09-12.json`: the displayed latest results; `allRuns.summary`
  covers eight models, 17 tasks and both configurations.
- `native-2026-09-11.json`: original measurements, retained unchanged.
- `upload-fix-2026-09-12.json`: the eight later CLI upload-task results,
  including failures. The latest view is not a new full-suite pass@1 run.

Keep these snapshots immutable. Add a dated snapshot for later measurements.
The website renderer lives in sanka-public; copy reviewed result snapshots there
without changing their bytes. Source hashes and measurement completeness remain
in the JSON. Do not publish raw credentials or campaign transcripts.

Run `python3 scripts/check_published_results.py` to verify source hashes, complete
task coverage and score/usage totals against the selected task cells.
