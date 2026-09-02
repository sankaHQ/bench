# Sanka PR #13 baseline provenance

Generated from Sanka commit `a286426bea32c08ce60578931649c1a026ab6c6f`
against the `drf-fastapi-001` fixture with:

```bash
sanka scan --settings fixture_project.settings
sanka plan --to fastapi
sanka apply --to fastapi \
  --plan-hash sha256:c83dfdc8647b10f7a90b28af7c4f02de29794cce43483238af0b50cd92973de3
```

The generated compatibility runtime was moved from its generated output folder
to the candidate root so the benchmark's fixed `target_app:app` entrypoint can
load every candidate uniformly. `source_root` was changed from `../../..` to `.`
to preserve the same resolved source repository after that packaging move. The
file was mechanically formatted, but no request-dispatch logic was changed.
