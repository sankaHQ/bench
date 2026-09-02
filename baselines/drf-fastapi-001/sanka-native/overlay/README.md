# Generated native FastAPI application

Sanka generated this application from plan `sha256:b75bfdde7be13b8c9a05865be37b61058d9ec17dcf3ffe2a1e37060a192fe894`.

Routes are declared with FastAPI decorators in `target_app.py` (`@app.get`,
`@app.post`, ...). Shared DRF-parity validation lives in `sanka_native.py`.
Persistence uses the retained Django ORM through the async facade in `sanka_store.py`. Generated `sanka_settings.py` removes DRF apps; Django is loaded for ORM access only, never as the request server.


Set `SANKA_DATABASE_URL` for PostgreSQL (the scan never stores a password).
SQLite uses the captured database path, overridable with `SANKA_DATABASE_URL`
or `SANKA_TEST_DB`.


`sanka test` writes `test_generated.py` and runs it. SQLite write tests
use an isolated copy of the database.

Format-suffix alias routes from the source router are dropped as a disclosed
contract change; clients negotiate content types with headers instead.

```bash
uv sync
uv run uvicorn target_app:app --reload
```
