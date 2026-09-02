# drf-fastapi-008 source fixture

This synthetic Django REST Framework application exposes one `Entry` domain
through three legacy API styles at once: `@api_view` functions, classic
`APIView` classes with an explicit dispatch lifecycle, and a router-backed
`ModelViewSet`. All three surfaces share one serializer, model, database, and
response contract.

The URL graph also includes regex captures for codes such as
`guide.v2+draft`, deliberately different trailing-slash rules by style, and a
route table appended from a formatted nested regex. The latter is valid Django
routing behavior but requires manual adaptation when reduced to a FastAPI path.

The fixture is intended for Python 3.12 with `django>=5.2,<6` and
`djangorestframework>=3.16,<4`.
