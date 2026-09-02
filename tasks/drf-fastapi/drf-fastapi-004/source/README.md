# drf-fastapi-004 synthetic fixture: signal-driven side effects

A DRF ledger application whose observable behavior partly lives outside its
views, in Django signals:

- `post_save(LedgerEntry, created=True)` applies the entry amount to
  `Account.balance` with an `F()` expression and appends an `entry-created`
  `AuditLog` row; `post_delete` reverses the posting and appends
  `entry-deleted` — the receivers are connected in `LedgerConfig.ready`;
- `Account.balance` is API-read-only: writes in create/update payloads are
  silently ignored, and the stored value is owned entirely by the signal
  side effects;
- `AuditLog` has no writing endpoint at all — rows appear only through the
  signals and the transfer action — but a read-only `GET /api/audit/` lists
  the trail in id order;
- a custom `POST /api/accounts/{pk}/transfer/` action locks both accounts in
  pk order inside `transaction.atomic`, validates the amount and the source
  balance, and on success writes the two ledger entries (`transfer-out` /
  `transfer-in`, balances updated by the signals) plus one `transfer` audit
  row; on failure everything rolls back;
- deleting an account cascades its entries, and each cascaded delete fires
  the `post_delete` receiver — the surviving audit trail records the cascade.

Synthetic, Apache-2.0, written for Sanka Migration Bench.
