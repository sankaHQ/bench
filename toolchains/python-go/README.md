# Go evaluator dependency cache

Locks copied verbatim from sankaHQ/extensions at
`10fb419e67b9f524406d999d4e3883494c3be8ce`,
`packages/sanka-extension-python-to-golang/src/sanka_extension_python_to_golang/locks/fiber-sqlite/`.
Apache-2.0; these are destination dependencies, not Sanka CLI/extension release pins.
They are supplied to both model arms and prepare the evaluator cache. They also
match the released Python-to-Go 0.1.0a17 wheel byte for byte (verified 2026-10-06).
Release wheels were downloaded for static inspection; no Go download or build has run.
Read versions from go.mod; a campaign selecting different versions needs new locks,
new image digests, and fresh Go control qualification. Never update the old CLI pins.

## Offline cache coverage

These checked-in locks are also supplied to both model arms; do not change them
just to expand evaluator cache coverage. During image preparation, `Dockerfile.go`
promotes the already locked Testify version to a root in its private copy, then
downloads its transitive requirements. This covers candidates whose module graph
exposes test dependencies omitted by the reference application's pruned graph.
The image runs `scripts/check_go_module_cache.sh` against a standalone Testify
graph with network lookup disabled. Candidate grading remains offline, and
historical source/baseline locks and images remain unchanged.
