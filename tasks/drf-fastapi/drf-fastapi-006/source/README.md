# drf-fastapi-006 source fixture

This synthetic Django REST Framework application exercises a three-level
writable graph: `Order -> OrderItem -> Adjustment`.

The collection and detail routes support create, full replacement, and partial
updates. Supplying `items` during either update replaces the entire child list;
omitting it during `PATCH` leaves the existing graph untouched. Both item SKUs
and adjustment codes are unique within their parent, and constraint failures
are translated into DRF-style nested index errors inside one atomic write.

The fixture is intended for Python 3.12 with `django>=5.2,<6` and
`djangorestframework>=3.16,<4`.
