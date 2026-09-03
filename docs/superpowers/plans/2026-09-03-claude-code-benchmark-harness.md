# Claude Code Benchmark Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make official Sanka model matrices use one pinned Claude Code harness with qualified model routes, isolated with/without-Sanka cells, durable resume fingerprints, and honest time/token/cost reporting.

**Architecture:** Extend the existing matrix coordinator, cell driver, candidate runner, evaluator schemas, and report collector. A v2 run manifest separates the pinned Claude Code harness from each inference treatment; immutable cell artifacts remain the cache, and a manifest-derived input digest prevents stale reuse. The with-Sanka arm installs the published Sanka skill project-locally inside its cell sandbox while the evaluator remains unchanged.

**Tech Stack:** Python 3.12+, stdlib subprocess/hashlib/json/pathlib, pytest, JSON Schema, existing `sanka-bench` reporting.

**Spec:** `docs/superpowers/specs/2026-09-03-claude-code-benchmark-harness-design.md`

## Global Constraints

- Official v2 matrices use the pinned Claude Code CLI for every model treatment.
- Native Claude subscription cells use OAuth and no gateway variables; gateway cells use gateway credentials and no subscription claim.
- Non-Claude routes remain experimental and require independently hashed provider/gateway model evidence.
- Official lanes are only `alone` and `with-sanka`; readiness-aware remains diagnostic.
- The with-Sanka lane installs `sanka skill install claude --scope project`; the alone lane exposes no Sanka skill, state, or binary.
- Reuse the current foreground coordinator, immutable pass@1 cells, one-time no-output provider retry, and single-writer aggregation.
- Unknown cost is `null`, never zero; subscription equivalent API cost is separate from actual marginal cost.
- Do not read, print, modify, or commit the existing local `.env`; no paid model request is part of implementation.
- Use TDD for every behavior change and commit each completed task independently.

---

### Task 1: Official manifest and route qualification

**Files:**
- Create: `scripts/qualify_claude_route.py`
- Modify: `scripts/run_agent_matrix.py`
- Modify: `scripts/run_matrix_cell.py`
- Test: `tests/test_claude_route_qualification.py`
- Test: `tests/test_agent_matrix.py`
- Test: `tests/test_matrix_cell.py`

**Interfaces:**
- Produces: `qualification_digest(path: Path) -> str`
- Produces: `validate_official_manifest(manifest: dict[str, Any], root: Path) -> None`
- Produces: v2 model fields `harness`, `requested_model_id`, `actual_model_id`, `route_kind`, `billing_mode`, `gateway_profile`, `qualification`, and `qualification_sha256`.

- [ ] **Step 1: Write failing manifest tests**

Add a v2 fixture and prove mixed harnesses, changed evidence, actual-model mismatch, and gateway/native billing confusion are rejected.

```python
def test_official_manifest_requires_claude_code(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    validate_official_manifest(value, tmp_path)
    value["models"][0]["harness"] = "codex"
    with pytest.raises(ValueError, match="Claude Code"):
        validate_official_manifest(value, tmp_path)


def test_official_manifest_rejects_changed_qualification(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    path = tmp_path / value["models"][0]["qualification"]
    path.write_text('{"status":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="qualification digest"):
        validate_official_manifest(value, tmp_path)
```

- [ ] **Step 2: Verify RED**

Run `uv run python -m pytest tests/test_agent_matrix.py tests/test_matrix_cell.py -q`.

Expected: import/assertion failures because v2 validation and route fields do not exist.

- [ ] **Step 3: Implement minimal v2 validation**

Keep v1 readable for historical fixtures. For schema `sanka-bench/model-matrix-run-manifest/v2`, require exactly the official lanes and Claude Code harness, validate the qualification path/digest/checks, and carry the route fields into both cell dataclasses.

```python
def qualification_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def validate_official_manifest(manifest: dict[str, Any], root: Path) -> None:
    if manifest.get("schema") != "sanka-bench/model-matrix-run-manifest/v2":
        return
    if manifest["execution"]["configurations"] != ["alone", "with-sanka"]:
        raise ValueError("official v2 configurations must be alone and with-sanka")
    for model in manifest["models"]:
        if model.get("harness") != "claude-code":
            raise ValueError("official v2 matrices require the Claude Code harness")
        path = (root / str(model["qualification"])).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("qualification path escapes the run directory")
        if qualification_digest(path) != model.get("qualification_sha256"):
            raise ValueError("qualification digest does not match the manifest")
        evidence = load_json(path)
        checks = evidence.get("checks", {})
        if any(
            checks.get(name) is not True
            for name in ("tool_use", "streaming", "terminal_event", "usage_accounting")
        ):
            raise ValueError("qualification checks are incomplete")
        if evidence.get("actual_model_id") != model.get("actual_model_id"):
            raise ValueError("qualification actual model does not match the manifest")
```

Wire this into both `plan` and `run`. Native subscription entries reject `gateway_profile`; gateway entries require it and use `api_key` billing.

- [ ] **Step 4: Write failing qualification utility tests**

Use a fake executable that emits Claude stream JSON and writes a fixed probe file. Assert exact identity, evidence digest, streaming, terminal, tool-use, and usage checks. Add negative tests for missing file and mismatched model evidence.

```python
def test_qualification_records_required_evidence(tmp_path: Path) -> None:
    record = qualify(
        claude_bin=fake_claude(tmp_path, creates_file=True),
        requested_model_id="gateway-alias",
        provider="example",
        provider_variant="standard",
        route_kind="gateway",
        billing_mode="api_key",
        gateway_profile="example-anthropic-v1",
        provider_evidence=provider_evidence(tmp_path, actual_model_id="gpt-5.6"),
        output=tmp_path / "qualification.json",
    )
    assert record["actual_model_id"] == "gpt-5.6"
    assert all(record["checks"].values())
```

- [ ] **Step 5: Verify RED, implement, and verify GREEN**

Run `uv run python -m pytest tests/test_claude_route_qualification.py -q`; expect import failure.

Implement a non-scored utility using a disposable workspace, fixed file write/read prompt, `-p`, `--output-format stream-json`, `--verbose`, `--max-turns 4`, and explicit model. It embeds only provider identities and SHA-256 evidence/transcript digests, never evidence contents or credentials.

```python
QUALIFICATION_TEXT = "sanka-bench-claude-route-qualified\n"


def sha256_path(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
```

Run `uv run python -m pytest tests/test_claude_route_qualification.py tests/test_agent_matrix.py tests/test_matrix_cell.py -q`; expect all selected tests to pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/qualify_claude_route.py scripts/run_agent_matrix.py scripts/run_matrix_cell.py tests/test_claude_route_qualification.py tests/test_agent_matrix.py tests/test_matrix_cell.py
git commit -m "feat: qualify Claude Code model routes"
```

---

### Task 2: Cell-local sandbox and Sanka skill

**Files:**
- Modify: `scripts/run_agent_candidate.py`
- Modify: `scripts/run_matrix_cell.py`
- Test: `tests/test_agent_harness.py`
- Test: `tests/test_matrix_cell.py`

**Interfaces:**
- Produces: `install_sanka_skill(sanka_bin: Path, workspace: Path, env: dict[str, str]) -> dict[str, str]`
- Produces: `route_environment(base: dict[str, str], cell: Cell) -> dict[str, str]`
- Produces: candidate options `--sandbox`, `--billing-mode`, `--actual-model-id`, `--route-kind`, and `--gateway-profile`.
- Produces: `Paths.sandbox`, `Paths.claude_config`, and cell-local `Paths.sanka_home`.

- [ ] **Step 1: Write failing isolation tests**

Prove different cells have different sandboxes, alone has no Sanka/gateway state, and with-Sanka installs exactly one Claude project skill with a verified digest.

```python
def test_install_sanka_skill_is_project_local(harness: object, tmp_path: Path) -> None:
    record = harness.install_sanka_skill(Path("/tools/sanka"), tmp_path, {"PATH": "/bin"})
    assert record["scope"] == "project"
    assert record["path"] == str(tmp_path / ".claude/skills/sanka-cli")
    assert record["content_sha256"] == "a" * 64
```

- [ ] **Step 2: Verify RED**

Run `uv run python -m pytest tests/test_agent_harness.py tests/test_matrix_cell.py -q`.

Expected: failures because persistent sandbox paths, route options, and skill installation are absent.

- [ ] **Step 3: Implement per-cell sandbox paths**

`run_matrix_cell.py` owns `sandboxes/<candidate-id>/`. The candidate runner uses `workspace/`, `claude-config/`, and `raw/` under that path, refuses a non-empty attempt workspace, and sets `CLAUDE_CONFIG_DIR`. Standalone calls without `--sandbox` retain a temporary directory.

```python
sandbox = root / "sandboxes" / cell.candidate_id
claude_config = sandbox / "claude-config"
sanka_home = sandbox / "sanka-home"
```

- [ ] **Step 4: Implement project-local skill installation**

Run the published CLI in JSON mode before Claude starts, verify the reported target remains inside the workspace, and compare the installed `SKILL.md` digest to `content_sha256`.

```python
command = [
    str(sanka_bin),
    "--output",
    "json",
    "skill",
    "install",
    "claude",
    "--scope",
    "project",
    "--project-dir",
    str(workspace),
]
```

Replace the official with-Sanka prompt's long usage overlay with one availability sentence; the installed skill owns usage guidance. Keep readiness-aware behavior separate.

- [ ] **Step 5: Implement route environment sanitation**

Allowlist `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_API_KEY`. Native subscription removes all three. Gateway requires a base URL plus exactly one auth variable. Credentials remain environment-only.

```python
auth = [name for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY") if env.get(name)]
if cell.route_kind == "gateway" and (not env.get("ANTHROPIC_BASE_URL") or len(auth) != 1):
    raise ValueError("gateway route requires a base URL and exactly one credential")
```

- [ ] **Step 6: Verify GREEN and commit**

Run `uv run python -m pytest tests/test_agent_harness.py tests/test_matrix_cell.py -q`; expect all selected tests to pass.

```bash
git add scripts/run_agent_candidate.py scripts/run_matrix_cell.py tests/test_agent_harness.py tests/test_matrix_cell.py
git commit -m "feat: isolate Claude Code benchmark cells"
```

---

### Task 3: Input-digest cache integrity

**Files:**
- Modify: `scripts/run_agent_matrix.py`
- Modify: `scripts/run_matrix_cell.py`
- Test: `tests/test_agent_matrix.py`
- Test: `tests/test_matrix_cell.py`

**Interfaces:**
- Produces: `cell_input_digest(manifest: dict[str, Any], *, task: str, model: dict[str, Any], config: str, sample: int) -> str`
- Produces: `CellSpec.input_digest: str`.

- [ ] **Step 1: Write failing digest/resume tests**

Prove model, prompt, Claude version, Sanka skill digest, and sample changes alter the digest. Prove generated/terminal artifacts with a missing or wrong digest become ambiguous.

```python
def test_resume_refuses_stale_input_digest(tmp_path: Path) -> None:
    cell = build_cells(manifest())[0]
    paths = artifacts(tmp_path, cell)
    paths.candidate.mkdir(parents=True)
    paths.log.parent.mkdir(parents=True)
    paths.log.write_text(
        "INPUT_DIGEST=sha256:" + "0" * 64 + "\nGENERATION_DONE run_exit=0 wall_seconds=1\n",
        encoding="utf-8",
    )
    assert cell_state(tmp_path, cell) == "ambiguous"
```

- [ ] **Step 2: Verify RED**

Run `uv run python -m pytest tests/test_agent_matrix.py tests/test_matrix_cell.py -q`.

Expected: failures because input digests do not exist.

- [ ] **Step 3: Implement canonical digest and state check**

Hash canonical JSON containing benchmark SHA, cell tuple, exact model dict, execution budgets/prompt digests, and pinned harness/Sanka toolchain values.

```python
encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
return "sha256:" + hashlib.sha256(encoded).hexdigest()
```

Write `INPUT_DIGEST=<value>` before generation. `cell_state` requires exactly one matching value whenever artifacts exist. Move the failed sandbox beside the log/candidate in the existing attempt-one incident ledger before retry.

Balance paired lane admission instead of always placing `alone` first: odd pairs admit
`alone` first and even pairs admit `with-sanka` first, while generated cells retain top
resume priority. Add a literal-order test covering two tasks and two samples.

- [ ] **Step 4: Verify GREEN and commit**

Run `uv run python -m pytest tests/test_agent_matrix.py tests/test_matrix_cell.py -q`; expect all selected tests to pass.

```bash
git add scripts/run_agent_matrix.py scripts/run_matrix_cell.py tests/test_agent_matrix.py tests/test_matrix_cell.py
git commit -m "feat: fingerprint benchmark cell inputs"
```

---

### Task 4: Claude usage, cost basis, and telemetry

**Files:**
- Modify: `scripts/run_agent_candidate.py`
- Modify: `scripts/run_matrix_cell.py`
- Modify: `src/sanka_bench/schema/candidate.schema.json`
- Modify: `src/sanka_bench/schema/result.schema.json`
- Test: `tests/test_agent_harness.py`
- Test: `tests/test_schema.py`
- Test: `tests/test_matrix_cell.py`

**Interfaces:**
- Produces: `claude_stats(stdout: str, *, billing_mode: str, requested_model_id: str, actual_model_id: str, measured_ms: float) -> dict[str, object]`
- Produces: `candidate/telemetry.json` with schema `sanka-bench/agent-cell-telemetry/v1`.
- Produces: expanded candidate stats copied unchanged into result provenance.

- [ ] **Step 1: Write failing usage/cost tests**

Use literal Claude result events with camelCase `modelUsage`. Prove cache-token classes are retained, subscription reported cost is not actual cost, API-key reported cost may populate actual cost, and missing usage stays null.

```python
def test_subscription_stats_keep_tokens_not_actual_cost(harness: object) -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "num_turns": 3,
            "duration_ms": 1200,
            "total_cost_usd": 1.25,
            "modelUsage": {
                "gateway-alias": {
                    "inputTokens": 100,
                    "cacheCreationInputTokens": 20,
                    "cacheReadInputTokens": 40,
                    "outputTokens": 30,
                }
            },
        }
    )
    stats = harness.claude_stats(
        stdout,
        billing_mode="subscription",
        requested_model_id="gateway-alias",
        actual_model_id="claude-sonnet-5",
        measured_ms=1300,
    )
    assert stats["cost_usd"] is None
    assert stats["reported_equivalent_cost_usd"] == 1.25
    assert stats["input_tokens"] == 100
    assert stats["cache_read_input_tokens"] == 40
```

- [ ] **Step 2: Verify RED**

Run `uv run python -m pytest tests/test_agent_harness.py tests/test_schema.py tests/test_matrix_cell.py -q`.

Expected: failures because Claude usage details, billing semantics, and telemetry fields are absent.

- [ ] **Step 3: Implement Claude result normalization**

Parse the final result event, sum model usage counters, retain per-client-model entries, and use measured wall time when the result omits duration.

```python
totals = {
    "input_tokens": sum(int(item.get("inputTokens") or 0) for item in usage.values()),
    "cache_creation_input_tokens": sum(
        int(item.get("cacheCreationInputTokens") or 0) for item in usage.values()
    ),
    "cache_read_input_tokens": sum(
        int(item.get("cacheReadInputTokens") or 0) for item in usage.values()
    ),
    "output_tokens": sum(int(item.get("outputTokens") or 0) for item in usage.values()),
}
```

For subscription, set `cost_usd` to null and retain `reported_equivalent_cost_usd`. For API key, use Claude Code's reported cost with basis `claude-code-reported`; do not derive prices here.

- [ ] **Step 4: Expand schemas and finish telemetry**

Add optional token counters, nullable and equivalent costs, model IDs, billing mode, and cost basis to both candidate/result stats schemas. Keep the evaluator tool-neutral: it continues copying `candidate.stats` only.

The candidate runner writes generation telemetry with transcript and overlay hashes. The cell driver appends setup/evaluation timing, wave metadata, report digest/status, and failure class through atomic replace.

```python
telemetry = {
    "schema": "sanka-bench/agent-cell-telemetry/v1",
    "input_digest": args.input_digest,
    "requested_model_id": args.model,
    "actual_model_id": args.actual_model_id,
    "provider": args.provider,
    "provider_variant": args.provider_variant,
    "route_kind": args.route_kind,
    "billing_mode": args.billing_mode,
    "timing": {"agent_wall_seconds": measured_ms / 1000},
    "usage": normalized_usage,
    "cost": normalized_cost,
}
```

- [ ] **Step 5: Verify GREEN and commit**

Run `uv run python -m pytest tests/test_agent_harness.py tests/test_schema.py tests/test_matrix_cell.py -q`; expect all selected tests to pass.

```bash
git add scripts/run_agent_candidate.py scripts/run_matrix_cell.py src/sanka_bench/schema/candidate.schema.json src/sanka_bench/schema/result.schema.json tests/test_agent_harness.py tests/test_schema.py tests/test_matrix_cell.py
git commit -m "feat: record Claude benchmark telemetry"
```

---

### Task 5: Paired quality, time, token, and cost reports

**Files:**
- Modify: `src/sanka_bench/statistics.py`
- Modify: `src/sanka_bench/report.py`
- Test: `tests/test_statistics.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `paired_numeric_interval(treatment: Sequence[float], control: Sequence[float], *, confidence: float = 0.95, resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED) -> Interval`
- Produces: row fields `tokens`, `reported_equivalent_cost_usd`, and `agent_seconds_per_verified_route`.
- Produces: top-level `comparisons` pairing `<treatment>-alone` with `<treatment>-with-sanka`.

- [ ] **Step 1: Write failing paired-report tests**

Prove unknown cost stays null instead of zero; tokens/time aggregate per sample; comparisons align the same task/sample; readiness-aware rows are excluded.

```python
def test_unknown_cost_is_not_zero(reports_dir: Path) -> None:
    data = collect(reports_dir)
    row = next(row for row in data["rows"] if row["family"] == "claude-code-subscription-alone")
    assert row["cost_usd"] is None
    assert row["reported_equivalent_cost_usd"] == pytest.approx(2.0)


def test_report_pairs_same_model_lanes(reports_dir: Path) -> None:
    comparison = collect(reports_dir)["comparisons"][0]
    assert comparison["treatment"] == "claude-code-gpt-5-6"
    assert comparison["quality_delta"]["estimate"] == pytest.approx(0.5)
    assert comparison["agent_seconds_delta"]["estimate"] == pytest.approx(-60.0)
```

- [ ] **Step 2: Verify RED**

Run `uv run python -m pytest tests/test_statistics.py tests/test_report.py -q`.

Expected: failures because numeric paired intervals/comparisons are absent and cost is currently coerced to zero.

- [ ] **Step 3: Implement deterministic numeric paired intervals**

Reuse the existing seed and percentile helper; pair before resampling and define delta as `with_sanka - alone`.

```python
def paired_numeric_interval(
    treatment: Sequence[float],
    control: Sequence[float],
    *,
    confidence: float = 0.95,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> Interval:
    if len(treatment) != len(control):
        raise ValueError("treatment and control values must align")
    differences = [left - right for left, right in zip(treatment, control, strict=True)]
    estimate = sum(differences) / len(differences) if differences else 0.0
```

- [ ] **Step 4: Aggregate honest telemetry and comparisons**

Track cost presence separately: `cost_usd` exists only when every included task-sample has actual cost. Sum token classes and divide cohort totals by sample count using the existing convention. Pair only exact `-alone` and `-with-sanka` family suffixes with the same prefix.

```python
def treatment_key(family: str) -> tuple[str, str] | None:
    for suffix, lane in (("-with-sanka", "with-sanka"), ("-alone", "alone")):
        if family.endswith(suffix):
            return family.removesuffix(suffix), lane
    return None
```

Add a compact paired-effects HTML table beneath the quality tally. Keep fully migrated as the headline and never combine dimensions into one score.

- [ ] **Step 5: Verify GREEN and commit**

Run `uv run python -m pytest tests/test_statistics.py tests/test_report.py -q`; expect all selected tests to pass.

```bash
git add src/sanka_bench/statistics.py src/sanka_bench/report.py tests/test_statistics.py tests/test_report.py
git commit -m "feat: report paired Sanka benchmark effects"
```

---

### Task 6: Credential and artifact safety, docs, and verification

**Files:**
- Create: `.env.example`
- Modify: `.gitignore`
- Modify: `scripts/run_agent_matrix.py`
- Modify: `docs/measurement-runs.md`
- Modify: `README.md`
- Test: `tests/test_agent_matrix.py`

**Interfaces:**
- Produces: `secret_hits(root: Path, secret_values: Sequence[str]) -> list[str]`.
- Produces: `artifact_issues(root: Path, cells: Sequence[CellSpec]) -> list[str]`.
- Produces: publication gate before aggregate output.

- [ ] **Step 1: Write failing secret-scan tests**

Prove a credential copied into a transcript blocks aggregation without printing its value; clean artifacts pass; short placeholders are ignored.

```python
def test_secret_scan_reports_path_without_value(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/run.log").write_text("leaked-secret-value", encoding="utf-8")
    assert secret_hits(tmp_path, ["leaked-secret-value"]) == ["logs/run.log"]


def test_secret_scan_ignores_short_placeholders(tmp_path: Path) -> None:
    (tmp_path / "report.json").write_text("test", encoding="utf-8")
    assert secret_hits(tmp_path, ["", "test"]) == []
```

- [ ] **Step 2: Verify RED and implement gate**

Run `uv run python -m pytest tests/test_agent_matrix.py -q`; expect import failure.

Scan regular files under the run root for allowlisted credential values of at least eight characters and known provider-key prefixes. Return only relative paths, never matched text. Also verify every terminal/generated cell has the expected artifact count and that telemetry hashes match the transcript, candidate, and report when present. Run both gates after workers finish and before aggregation; on a hit, emit a failure event, record failure, and skip aggregate output.

```python
def secret_hits(root: Path, values: Sequence[str]) -> list[str]:
    needles = [value.encode() for value in values if len(value) >= 8]
    hits = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if any(needle in path.read_bytes() for needle in needles):
            hits.append(path.relative_to(root).as_posix())
    return hits
```

- [ ] **Step 3: Add safe environment files and operator docs**

Add `.env` to `.gitignore`. Track `.env.example` containing names and empty values only:

```dotenv
ANTHROPIC_BASE_URL=
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_API_KEY=
```

Document v2 fields, qualification command, subscription/API/gateway cost semantics, project-local skill installation, sandbox locations, digest resume, secret scan, and paid-run authorization. Replace README examples that present Codex as an official matrix harness with Claude Code treatments.

- [ ] **Step 4: Run focused and repository checks**

```bash
uv run python -m pytest tests/test_agent_matrix.py tests/test_matrix_cell.py tests/test_agent_harness.py tests/test_claude_route_qualification.py tests/test_statistics.py tests/test_report.py tests/test_schema.py -q
uv run ruff format .
uv run ruff check --fix .
uv run mypy
uv run sanka-bench validate
make check
```

Expected: focused and full tests pass; Ruff/mypy have no errors; 11 tasks, 44 baseline candidates, and 3 schemas validate. Do not run paid candidates, `make baselines`, or `make docker-baselines`.

- [ ] **Step 5: Inspect and commit the final slice**

```bash
git diff --check
git status --short
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- . ':!.env'
```

Confirm `.env` is neither read nor staged and no run artifact or credential appears.

```bash
git add .env.example .gitignore scripts/run_agent_matrix.py docs/measurement-runs.md README.md tests/test_agent_matrix.py
git commit -m "docs: publish Claude harness run contract"
```

- [ ] **Step 6: Review and finish**

Use `superpowers:requesting-code-review` against `origin/main...HEAD`. Resolve every Critical or Important finding with a new failing test before production changes. Rerun `make check`, then use `superpowers:finishing-a-development-branch` to present the three integration choices.
