# drf-fastapi-010 source fixture

This synthetic Django REST Framework application models orders with a strict
state machine and optimistic concurrency. Draft orders may be submitted or
cancelled, submitted orders may be approved or cancelled, approved orders may
be shipped, and shipped or cancelled orders are terminal.

Every successful mutation advances the order version exactly once and records
one `OrderEvent`. PATCH and transition requests must provide the current
version. Stale requests, malformed targets, and illegal transitions return
distinct deterministic errors without changing either database table.

The fixture is intended for Python 3.12 with `django>=5.2,<6` and
`djangorestframework>=3.16,<4`.
