# drf-fastapi-002 synthetic fixture: token auth + object permissions

A DRF bulletin-board application exercising the authentication and permission
surface of the benchmark lane:

- `TokenAuthentication` backed by `rest_framework.authtoken` (database tokens);
- `IsAuthenticated` plus the canonical `IsAuthorOrReadOnly` object permission:
  any authenticated user reads all posts, only the author mutates their own;
- `perform_create` injects the authenticated user as author server-side;
- 401 variants (missing, invalid, malformed credentials) with
  `WWW-Authenticate` behavior, and 403 on foreign-object writes.

Synthetic, Apache-2.0, written for Sanka Migration Bench.
