# drf-fastapi-011 source fixture

This synthetic Django REST Framework application exposes paginated account
metrics derived from related transaction rows. The account list combines
`Count` and filtered `Sum` annotations with deterministic ordering and
`SerializerMethodField` values derived from prefetched transactions.

Transaction create, patch, and delete endpoints let a scenario mutate the
related rows before reading the aggregates again. A separate summary endpoint
returns region groups, string-form decimal totals, zero-valued groups with no
transactions, and a deterministic empty result when no accounts exist.

The fixture is intended for Python 3.12 with `django>=5.2,<6` and
`djangorestframework>=3.16,<4`.
