# Tenant-scoped idempotent transfers

A new independent source family combining tenant authentication, exact DRF field validation, atomic balances, per-tenant idempotency and audit parity. Public cases illustrate the contract; hidden multi-request cases cover conflicts, validation ordering, cross-tenant isolation, exhaustion and replay. Reuse source services and ORM where valid, without importing DRF serving code.
