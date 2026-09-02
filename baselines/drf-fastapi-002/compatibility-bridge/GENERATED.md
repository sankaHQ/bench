# Sanka compatibility-bridge baseline provenance (drf-fastapi-002)

Generated from Sanka commit `486c0a6c0a3529f8d182a94a32a7dce5c96f4fb1`
(merged PR #15) against the `drf-fastapi-002` fixture with:

```bash
sanka scan .
sanka plan --to fastapi --strategy compatibility
sanka apply --root .
```

Packaged the same way as the drf-fastapi-001 bridge baseline: the generated
`sanka_compat.py` runtime was saved as the candidate's fixed `target_app.py`
entrypoint with `app = create_app()` appended, and `source_root` in the
manifest was set to `.` because the overlay merges into the workspace root.
No request-dispatch logic was changed.

This baseline is a permanent negative control: it must preserve behavior
(including token authentication and object permissions, which it inherits by
dispatching into Django) while failing the native-target gate on recorded
serving evidence.
