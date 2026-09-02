# drf-fastapi-007 source fixture

This synthetic Django REST Framework application makes response representation
part of the migration contract. A record collection uses encoded cursor
pagination, composable search and ordering filters, and deterministic primary
key tie-breakers. Decimal values remain two-place strings, while aware
datetimes render in `Asia/Tokyo` rather than UTC.

Record details carry a content-derived `ETag`, `Cache-Control`, and `Vary`.
Matching `If-None-Match` requests return `304 Not Modified` with an empty body;
mutations change the validator exactly when serialized content changes.

The fixture is intended for Python 3.12 with `django>=5.2,<6` and
`djangorestframework>=3.16,<4`.
