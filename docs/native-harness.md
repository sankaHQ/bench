# Sanka native harness

`run_agent_candidate.py` now defaults to `--agent sanka-native`. It calls the
provider API directly. Claude Code, Codex CLI, their subscriptions, plugins,
memory, and session services are not needed. Explicit `--agent claude-code`
and `--agent codex` remain available to reproduce historical runs.

Only the harness changes. Tasks, public/hidden scenarios, candidate schema,
grader, pass@1 definition, and existing scores are unchanged.

## Execution

Both Sanka arms run `scan → plan → apply → test → verify` automatically.
The controller passes the exact core plan hash to apply, uses `--compact-dsl`,
and retains every command result. Generated files stay under `.sanka` until
the scaffold test finishes, so they do not invalidate the reviewed source
fingerprint. The existing add-only promotion helper installs them afterward.
FastAPI uses the extension's existing benchmark projection; Flask already
generates the required entrypoint. Planning selects the existing `pip` option,
so generated-app tests can use Python's own virtualenv support without finding
a globally installed package manager. Home and temporary paths stay isolated.

If public verification succeeds without warnings, the run ends without a
model request. Otherwise, the model receives the task contract and lifecycle
results, then uses `exec` for edits/tests, `read` for bounded file or saved-output
excerpts, and `verify` for public replay and seed registration. Commands run sequentially in the existing OS
sandbox. No provider credentials are forwarded to commands. The model-only
arm has `exec` and `read`; it gets no Sanka lifecycle, CLI, or Skill.

The Skills arm receives the exact hash-checked Skill installed by `sanka skill`
once in its initial prompt. It uses the existing installation format; no Claude
Code process is started. The CLI-only arm gets no Skill.

Scaffold testing and repaired-candidate verification have different scopes.
`test` can report manual gaps or generated-scope failures; these remain in the
record even if later public verification passes. Repairs never automatically
rerun apply. An unchanged verification result is reused until another command
or seed selection invalidates it. Read-only excerpts preserve verification.
Repeated failed finalization or structured verification stops when the failure
fields are unchanged, ignoring newly generated report paths. Public verification is not a benchmark score:
the unchanged independent evaluator still grades the frozen candidate.

## State, limits, and accounting

- Direct OpenAI Responses and Fireworks Chat Completions routes. Exact model
  identity is checked; there is no fallback model/provider. Reasoning defaults
  to `high`; official native matrices require it explicitly.
- `--max-turns` caps both model responses and model-requested tool calls.
  CLI lifecycle commands are counted separately. The wall deadline bounds
  requests, commands, and retry waits. Each command is limited to 120 seconds.
- Each response defaults to 8,192 output tokens, including reasoning. Set
  `--max-output-tokens` (matrix `execution.max_output_tokens`) explicitly for
  high-effort runs that need more room for reasoning and code. The limit is
  recorded in request/final evidence, included in cell identity, and reserved
  before each paid request. A response ending at its limit remains a recorded
  `incomplete_response`, never silently retried. Context defaults to
  120,000 serialized bytes; `--max-context-bytes` (matrix
  `execution.max_context_bytes`) pins a different ceiling with the same
  identity and evidence rules. It includes retained provider reasoning, not
  just visible conversation text. Exceeding it stops before another API call.
  Tool results show at most 6,000 characters with a
  path to the complete output. No paid summarizer or silent context eviction.
  OpenAI reasoning items/call IDs and Fireworks `reasoning_content` stay in order.
- At most two retries for explicit HTTP 429 rejection. No retries for ambiguous
  timeouts/5xx responses or failed candidate generation. At most three failed
  completion/repair rounds. Budget exhaustion freezes the current candidate;
  provider/protocol errors remain infrastructure failures.
- `native/events.jsonl` records requests, raw responses, lifecycle results,
  and tool events as they happen, with monotonic elapsed timestamps. Command
  and provider durations are aggregated in `phase_seconds`; provider retry sleeps
  are excluded. Coverage, candidate and infrastructure failures are distinct.
  Command timeouts are separate from a program returning exit code 124. `native/tools/` retains complete outputs;
  `native/state.json` checkpoints the conversation at termination/interruption.
  The matrix retains its existing resume rules for completed cells. Mid-call
  execution is not resumed automatically; interrupted mutations are not replayed.
- Usage comes from provider responses. Cached input is a subset of input,
  not added twice. Missing details or ambiguous usage remain null. No prices
  are guessed. With explicit `--price-in` and `--price-out` (USD/million), cost
  is a conservative estimate charging cached input at the full input rate.
  `--max-agent-cost-usd` also reserves a conservative allowance before each
  request. This is a local estimated-cost limit, not a provider billing guarantee.

## Running

Use the existing Python 3.12 fixture environment and a pinned Sanka installation
supporting compact lifecycle output. Select an exact provider model and export
only its `OPENAI_API_KEY` or `FIREWORKS_API_KEY` through the existing secret loader.
The following command incurs provider charges when model work is needed:

```sh
uv run python scripts/run_agent_candidate.py \
  --agent sanka-native --provider openai --model "$MODEL_ID" \
  --reasoning-effort high --task tasks/drf-flask/drf-flask-005 \
  --candidate-id sanka-native-model-with-sanka \
  --sanka-bin "$SANKA_BIN" --out "$RUN_DIR/candidate" \
  --sandbox "$RUN_DIR/sandbox" --max-turns 60 --wall-clock-seconds 900
```

Use `-sanka-cli` for CLI only; use `-alone` and omit `--sanka-bin` for model only.
Use new run directories; never overwrite an earlier pass@1 attempt.

Before admitting a paid route to an official matrix, run the small, separately
authorized round-trip probe:

```sh
uv run python scripts/qualify_native_route.py \
  --provider openai --model "$MODEL_ID" --out "$RUN_DIR/qualifications/native.json"
```

Native v2 manifests use `harness: sanka-native`, `reasoning_effort: high`,
`billing_mode: api_key`, `gateway_profile: null`, and
`execution.sanka_workflow: native-lifecycle-v1`. The route is `openai-responses`
for OpenAI or `openai-chat` for Fireworks. Record `toolchain.native_version`
and `native_bin_sha256` from the qualification's `native` record, plus its
qualification digest. No `claude_bin` or `codex_bin` is needed. Pin provider
prices on the model record if using a cost cap. The harness hash and workflow
are part of the cell digest; old Claude results cannot satisfy native cells.

## Reference study

The implementation uses design ideas, not either project's runtime:

- [Pi agent loop, pinned revision](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/agent/src/agent-loop.ts):
  separate provider messages from tool execution, ordered results, reject
  truncated tool calls, and stop at a well-defined turn boundary.
- [Pi session retry handling](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/agent-session.ts):
  bounded retry events/backoff. Here only explicit rate rejections are retried.
- [Codex tool orchestrator](https://github.com/openai/codex/blob/02d4529f55342dee025a5c13f612b72488dfa627/codex-rs/core/src/tools/orchestrator.rs):
  centralize execution policy at the tool boundary. This runner reuses the
  existing benchmark sandbox and never escalates tool permissions.
- [Codex context history](https://github.com/openai/codex/blob/02d4529f55342dee025a5c13f612b72488dfa627/codex-rs/core/src/context_manager/history.rs):
  bound model-facing tool output while retaining execution evidence.
- [OpenAI stateless reasoning](https://developers.openai.com/api/docs/guides/deployment-checklist)
  and [Fireworks interleaved reasoning](https://docs.fireworks.ai/guides/reasoning):
  retain provider-required reasoning state across tool turns.

No TUI, MCP host, subagents, plugin framework, vector memory, or general-purpose
planning engine. Token/cost/latency/pass@1 improvements require a new controlled
paid comparison; offline checks alone do not establish them.
