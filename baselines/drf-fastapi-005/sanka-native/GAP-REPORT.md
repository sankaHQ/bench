# Sanka native migration gap report

Plan `sha256:09e0249c005628c35677d7073663f7df0d47df87bb82144443233bbc5c6a4f0b` — native readiness 12% (1/8 non-alias routes generatable).

The source application remains the specification. Every route below
still needs a hand-written handler whose behavior is verified against
the source application, not assumed from generated code.

## Routes needing manual adaptation (7)

- `GET /api/documents/` — stubbed to answer 501 in the generated app
  - `SANKA_DRF_AUTH_PERMISSIONS_UNSUPPORTED`: Authentication/permission classes are outside AllowAny or the supported TokenAuthentication + IsAuthenticated owner pattern; authentication: documents.authentication.ExpiringTokenAuthentication, rest_framework.authentication.SessionAuthentication; permissions: rest_framework.permissions.AllowAny
- `POST /api/documents/` — stubbed to answer 501 in the generated app
  - `SANKA_DRF_AUTH_PERMISSIONS_UNSUPPORTED`: Authentication/permission classes are outside AllowAny or the supported TokenAuthentication + IsAuthenticated owner pattern; authentication: documents.authentication.ExpiringTokenAuthentication, rest_framework.authentication.SessionAuthentication; permissions: rest_framework.permissions.AllowAny
- `DELETE /api/documents/{pk}/` — stubbed to answer 501 in the generated app
  - `SANKA_DRF_AUTH_PERMISSIONS_UNSUPPORTED`: Authentication/permission classes are outside AllowAny or the supported TokenAuthentication + IsAuthenticated owner pattern; authentication: documents.authentication.ExpiringTokenAuthentication, rest_framework.authentication.SessionAuthentication; permissions: rest_framework.permissions.AllowAny
- `GET /api/documents/{pk}/` — stubbed to answer 501 in the generated app
  - `SANKA_DRF_AUTH_PERMISSIONS_UNSUPPORTED`: Authentication/permission classes are outside AllowAny or the supported TokenAuthentication + IsAuthenticated owner pattern; authentication: documents.authentication.ExpiringTokenAuthentication, rest_framework.authentication.SessionAuthentication; permissions: rest_framework.permissions.AllowAny
- `PATCH /api/documents/{pk}/` — stubbed to answer 501 in the generated app
  - `SANKA_DRF_AUTH_PERMISSIONS_UNSUPPORTED`: Authentication/permission classes are outside AllowAny or the supported TokenAuthentication + IsAuthenticated owner pattern; authentication: documents.authentication.ExpiringTokenAuthentication, rest_framework.authentication.SessionAuthentication; permissions: rest_framework.permissions.AllowAny
- `PUT /api/documents/{pk}/` — stubbed to answer 501 in the generated app
  - `SANKA_DRF_AUTH_PERMISSIONS_UNSUPPORTED`: Authentication/permission classes are outside AllowAny or the supported TokenAuthentication + IsAuthenticated owner pattern; authentication: documents.authentication.ExpiringTokenAuthentication, rest_framework.authentication.SessionAuthentication; permissions: rest_framework.permissions.AllowAny
- `POST /api/documents/{pk}/review/` — stubbed to answer 501 in the generated app
  - `SANKA_DRF_CUSTOM_ACTION_UNSUPPORTED`: Custom or unsupported viewset actions are present: review

## DRF parity checklist for hand-written handlers

Behavior that most often breaks exact parity when porting DRF by hand — every
item below has cost a real migration its last few percent:

- DRF stamps an `Allow` header on every response, including 400/404 (HEAD is
  added for GET; OPTIONS is always present).
- 404 has two flavors: a missing object renders the model's "No X matches the
  given query." while an invalid pk type renders the generic "Not found."
- Field-level null checks run before type checks: `{"items": null}` must yield
  `["This field may not be null."]`, not a list-type error.
- "may not be blank" (blank string) and "This field is required." (absent or
  null-file field) are different validations with different wording.
- Redirect responses carry an absolute `Location` URI
  (`request.build_absolute_uri`), never a relative path — and a framework's
  implicit trailing-slash redirect is not equivalent to the source's redirect
  view.
- Auth failures have exact strings and a `WWW-Authenticate` header; session
  authentication enforces CSRF even for API clients (Django's test client
  skips that only until `enforce_csrf_checks=True`).
- Unique-constraint violations surface as the model's own message (e.g.
  "order with this reference already exists.") as a 400 response — an
  unhandled database IntegrityError that kills the serving process is not
  parity.
- Django's test client omits `Content-Length`; adding or keeping the header
  where the source has none is a visible difference.

## Machine-readable detail

`plan-fastapi.json` beside this file carries per-route strategies and
adaptation codes; a generated app's `sanka-manifest.json` repeats the
inventory under `unsupported_routes` and `skipped_routes`.
