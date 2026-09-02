# Native reference for drf-fastapi-002

Hand-written native FastAPI implementation of the bulletin fixture.

The serving process must not load DRF, so:

- `target_settings.py` strips every `rest_framework*` app from
  `INSTALLED_APPS` (including `rest_framework.authtoken`);
- token authentication reads the existing `authtoken_token` table through an
  unmanaged model mirror defined in the serving layer — the table itself is
  still created and seeded by the source application's migrations;
- authentication, permission, validation, 404, and `Allow`/`WWW-Authenticate`
  behavior reimplement DRF semantics natively with the exact default strings.
