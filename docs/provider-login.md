# Provider login

> **Experimental — DWYOR (Do With Your Own Risk).** Sanka Bench's login
> integration is unofficial and is not endorsed by OpenAI or Anthropic. It
> delegates sign-in to their official CLIs; it does not provide a provider-approved
> subscription API for the native harness. Authentication behavior and provider
> terms may change. You are responsible for your account, usage limits, and
> compliance with the applicable provider terms. Subscription-backed benchmark
> generation uses an experimental managed transport. Independent GPT workers are
> serialized; live expiry/revocation recovery is not yet qualified.

Install the [Codex CLI](https://learn.chatgpt.com/docs/cli), then run:

```bash
sanka-bench login --provider chatgpt --device-auth
sanka-bench login status --provider chatgpt
sanka-bench logout --provider chatgpt

# Requires the official Claude Code CLI; opens its browser login flow.
sanka-bench login --provider claude
sanka-bench login status --provider claude
sanka-bench logout --provider claude
```

`sanka-bench login` also defaults to device authentication. Open the verification
URL printed by Codex, sign in with your ChatGPT subscription account, and enter
the one-time code. Device login must be enabled in your ChatGPT account or
workspace; see [OpenAI authentication](https://learn.chatgpt.com/docs/auth).
Ctrl-C cancels the pending login. Status and logout operate on Sanka Bench's
session, not your regular Codex login.

ChatGPT is the default provider. Codex manages its login and token refresh. Credentials stay in the private
`~/.sanka-bench/codex/` directory, outside repositories and benchmark artifacts.
Treat that directory like a password; do not commit or share it. Sanka Bench
does not inherit API keys or your existing `CODEX_HOME` for these commands.
Login, status, and logout take an exclusive process lock: a competing command
fails with `session is busy` instead of changing credentials concurrently.
The lock is released when the owning processes exit; do not delete its file.

The native harness supports ChatGPT subscriptions with `--provider openai
--billing-mode subscription`. It delegates inference and refresh to Codex App Server,
with built-in environments and ambient plugins disabled. Only the benchmark's
sandboxed tools can access task files. Each cell gets a fresh ephemeral conversation;
credentials remain outside cell artifacts. The coordinator pins the Codex binary.
API keys are stripped, and authentication failures do not fall back to API billing.
The harness supplies its own base instructions so model defaults cannot require
unavailable editing tools such as `apply_patch`. File edits use the advertised
`bench_exec` tool and ordinary shell commands or Python in the isolated workspace.

One subscription cell holds the account lock for its full lifetime. Run different
API providers alongside it; do not start independent concurrent GPT workers.
Codex still adds environment context and manages context/output limits, so this transport
is reported separately from direct API runs. Tool count and wall-time limits remain
harness-enforced. Token usage includes Codex overhead; actual subscription cost
stays null. Native stats also contain `api_equivalent`, priced from saved response
usage at OpenAI Standard API rates (source and check date included). Interrupted
turns retain an observed cost lower bound; unreported tokens are not extrapolated.
Cache reads/writes are input subsets, and reasoning is included in output. The
estimate applies long-context pricing per response and is not a subscription invoice.
Rates must be rechecked before future campaigns. Native response/context byte settings do
not impose equivalent limits inside Codex's managed model loop.

For Claude, Bench launches the unmodified `claude auth login --claudeai` command
with a private `~/.sanka-bench/claude/` configuration directory. Claude Code owns
credential storage (including its macOS Keychain), browser authentication, and
refresh; Bench does not read or export its tokens. `--device-auth` is ChatGPT-only.
Inherited Anthropic API keys, bearer tokens, and OAuth overrides are removed.
Each provider has its own command lock, so logging out of one does not invoke the
other provider's CLI. These locks coordinate Bench commands, not independently
started vendor CLIs.

The native harness supports Claude subscriptions with `--provider anthropic
--billing-mode subscription`. It runs the unmodified Claude Code binary as a
managed transport; it never reads or forwards subscription tokens to an HTTP
adapter. Built-in tools, skills, hooks, plugins, and ambient MCP servers are
disabled. Only the harness-owned `exec`, `read`, and treatment-only `verify` MCP
tools can access the isolated task workspace. Sanka retains scan → plan → apply
→ test → verify, sandbox execution, limits, and independent grading.

A Claude account lease serializes cells and login/logout. Authentication or quota
errors stop admission without API fallback. Verification stops the managed child
before another inference request; missing final usage remains a lower bound.
Results identify `claude-managed-subscription`, include CLI version and binary
hash, and retain streamed usage and final-result reconciliation. Anthropic
Standard API-equivalent estimates use current prices and separate 5-minute from
1-hour cache writes; the CLI-reported dollar estimate is retained as raw evidence
and may use older prices. Managed transport context/output limits and auxiliary
behavior differ from a direct API route. Qualification rejects unexpected tools,
model substitution, auxiliary models, or missing usage.
See [Anthropic authentication boundaries](https://code.claude.com/docs/en/legal-and-compliance).

Simultaneous subscription workers remain blocked. Cross-provider parallelism must
pass the normal isolation and boot qualification first. Login and tool-round-trip
tests do not prove recovery from a revoked or expired session; authentication errors
stop admission for investigation and any rerun retains its original attempt.
