# drf-fastapi-009 source fixture

This synthetic Django REST Framework application stores small uploaded files on
a Django `FileField`. The collection endpoint accepts real multipart form data,
validates the file extension and byte size, and records deterministic metadata.
Detail responses expose that metadata, while a dedicated download endpoint
returns the original bytes with an attachment disposition.

Every endpoint also has DRF format-suffix routes restricted to `.json` and
`.api`. The `.api` suffix uses a vendor JSON media type, while binary downloads
remain byte-for-byte identical across canonical and suffixed routes. The
fixture deliberately uses no `ImageField` or image-processing dependency.

The fixture is intended for Python 3.12 with `django>=5.2,<6` and
`djangorestframework>=3.16,<4`.
