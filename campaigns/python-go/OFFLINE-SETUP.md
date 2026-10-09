# Offline Go setup

A transient module-proxy failure must not consume a model attempt. Before a campaign,
prepare and qualify a ZIP of the pinned evaluator image's Go module download cache.
The ZIP contains only `cache/download/...` files. Record its absolute path and
`sha256:` digest as `go_toolchain.module_seed.path` and `.sha256` in the manifest.
Qualification evidence must include this exact toolchain object.

The runner verifies the archive digest and creates a private module cache before
the model timer starts. It disables remote module and checksum-server access for
Go commands and the Sanka extension. Go still verifies downloads against go.sum.
Missing dependencies stop setup rather than trigger network fallback. Never seed
from an agent candidate, share writable caches, or include generated application code.

Qualify all four source/scaffold dependency graphs and the evaluator before model
calls. Keep task inputs, grading, prompts, numeric limits and released CLI/extension
pins unchanged. Disclose offline preparation as a setup/timing methodology change.

A new authorized cohort never overwrites earlier results. Keep interrupted attempts
and their usage; they are ungraded infrastructure events, never model failures or
passes. Do not retry graded failures automatically. After a pre-model setup failure,
repair and requalify setup before admitting a separately recorded attempt.
