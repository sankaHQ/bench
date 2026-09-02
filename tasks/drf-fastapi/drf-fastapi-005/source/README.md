# drf-fastapi-005 synthetic fixture: authentication and permission matrix

A DRF document application whose request matrix combines authentication order,
action-level permissions, and detail-only object permissions:

- `ExpiringTokenAuthentication` followed by `SessionAuthentication` on the same
  `ModelViewSet`; malformed, invalid, and expired token credentials fail before
  DRF can fall through to an otherwise valid session, and unsafe session writes
  retain DRF's CSRF enforcement;
- `get_permissions()` makes list public, create authenticated, destroy
  staff-only, and ordinary detail operations owner-only;
- a custom `review` action selects its staff-only permission class through the
  same `get_permissions()` branch and deliberately lets staff review documents
  they do not own;
- authentication runs before permission checks, while object permission checks
  run only after a detail object is loaded. The graded 401/403/404 cases pin
  those ordering rules together with exact `WWW-Authenticate` and `Allow`
  headers.

Synthetic, Apache-2.0, written for Sanka Migration Bench.
