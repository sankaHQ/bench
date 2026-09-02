# Sanka Migration Bench

This repository is the independent evaluator for repository-level migrations.

## Boundaries

- Keep evaluator logic tool-neutral. Do not special-case Sanka candidates.
- Keep hidden evaluator material outside this repository.
- Pin source commits, dependency locks, container digests, task schemas, and
  result schemas.
- A behavior pass never compensates for a failed native-target-compliance gate.
- Django ORM use is allowed in the DRF-to-FastAPI lane; DRF request handling,
  Django ASGI mounting, and proxying are forbidden in native candidates.
- Do not publish datasets, make the repository public, or deploy hosted
  evaluation without explicit approval.

## Checks

```bash
uv sync --frozen --extra fixture --group dev
make check
make baselines
make docker-baselines
```

All AI-authored changes use the workspace `sanka-pr-flow` and require exact-head
human approval before merge.
