# Sanka compatibility-bridge baseline provenance (drf-fastapi-003)

Generated from Sanka commit `6c13461ac83952ed3711f6bdbd35712016f602c2`
(merged PR #17) against the `drf-fastapi-003` fixture with:

```bash
sanka scan .
sanka plan --to fastapi --strategy compatibility
sanka apply --root .
```

Packaged like the other bridge baselines: the generated `sanka_compat.py`
runtime saved as the fixed `target_app.py` entrypoint with
`app = create_app()` appended, and manifest `source_root` set to `.`.
No request-dispatch logic was changed.

For the record, the native plan on this fixture reports 57% readiness with
all six viewset routes needing manual adaptation — writable nested
serializers are outside the converter's envelope today, so 003 has no
passing converter baseline. The benchmark leads the converter again.
