# Conditional document API

Migrate a tenant-scoped document service from DRF to native Flask while retaining Django ORM models and domain logic. GET/HEAD support weak If-None-Match comparisons and 304 responses; PATCH/DELETE require strong If-Match comparisons or a wildcard. Updates increment revisions and atomically append revision events. Deleted and foreign-tenant documents are invisible. Preserve DRF field validation and its precedence over write preconditions, exact response bodies/statuses, ETag/Cache-Control/Allow/WWW-Authenticate headers, and database mutations.

This is an independently authored synthetic source family. Public scenarios sample the contract; grading adds boundary and sequence cases.
