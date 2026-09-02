"""Native FastAPI port of the DRF `widgets` API.

Django is used for the ORM only: the app registry is populated from
fixture_project.serving_settings, which drops rest_framework from
INSTALLED_APPS. Nothing in this module imports rest_framework or any of
Django's request-serving machinery (django.core.asgi/wsgi/handlers,
django.test) -- all HTTP handling is native FastAPI/Starlette.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fixture_project.serving_settings")

import django

django.setup()

from django.core.exceptions import ObjectDoesNotExist  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

from widgets.models import Widget  # noqa: E402

app = FastAPI()

_MISSING = object()
_MAX_NAME_LENGTH = 80
_DECIMAL_TRIM = re.compile(r"\.0*\s*$")


def _widget_dict(widget: Widget) -> dict[str, Any]:
    return {"id": widget.id, "name": widget.name, "quantity": widget.quantity}


def _validate_name(value: Any, errors: dict[str, list[str]], required: bool) -> Any:
    if value is _MISSING:
        if required:
            errors["name"] = ["This field is required."]
        return _MISSING
    if value is None:
        errors["name"] = ["This field may not be null."]
        return _MISSING
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        errors["name"] = ["Not a valid string."]
        return _MISSING
    text = str(value)
    if text.strip() == "":
        errors["name"] = ["This field may not be blank."]
        return _MISSING
    if len(text) > _MAX_NAME_LENGTH:
        errors["name"] = [
            f"Ensure this field has no more than {_MAX_NAME_LENGTH} characters."
        ]
        return _MISSING
    return text


def _validate_quantity(value: Any, errors: dict[str, list[str]], required: bool) -> Any:
    if value is _MISSING:
        if required:
            errors["quantity"] = ["This field is required."]
        return _MISSING
    if value is None:
        errors["quantity"] = ["This field may not be null."]
        return _MISSING
    try:
        cleaned = int(_DECIMAL_TRIM.sub("", str(value)))
    except (ValueError, TypeError):
        errors["quantity"] = ["A valid integer is required."]
        return _MISSING
    if cleaned < 0:
        errors["quantity"] = ["Ensure this value is greater than or equal to 0."]
        return _MISSING
    return cleaned


def _parse_body(raw: bytes) -> tuple[Any, JSONResponse | None]:
    if not raw:
        return {}, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, JSONResponse(
            {"detail": f"JSON parse error - {exc}"}, status_code=400
        )
    if not isinstance(data, dict):
        return None, JSONResponse(
            {
                "non_field_errors": [
                    f"Invalid data. Expected a dictionary, but got {type(data).__name__}."
                ]
            },
            status_code=400,
        )
    return data, None


def _validate_payload(data: dict[str, Any], partial: bool) -> tuple[dict[str, Any], dict[str, list[str]]]:
    errors: dict[str, list[str]] = {}
    cleaned: dict[str, Any] = {}

    name = _validate_name(data.get("name", _MISSING), errors, required=not partial)
    if name is not _MISSING:
        cleaned["name"] = name

    quantity = _validate_quantity(data.get("quantity", _MISSING), errors, required=not partial)
    if quantity is not _MISSING:
        cleaned["quantity"] = quantity

    return cleaned, errors


class _LookupResult:
    __slots__ = ("widget", "error")

    def __init__(self, widget: Widget | None, error: JSONResponse | None) -> None:
        self.widget = widget
        self.error = error


def _lookup_widget(pk: str) -> _LookupResult:
    try:
        pk_int = int(pk)
    except ValueError:
        return _LookupResult(None, JSONResponse({"detail": "Not found."}, status_code=404))
    try:
        return _LookupResult(Widget.objects.get(pk=pk_int), None)
    except ObjectDoesNotExist:
        return _LookupResult(
            None,
            JSONResponse(
                {"detail": "No Widget matches the given query."}, status_code=404
            ),
        )


@app.get("/api/")
def api_root(request: Request) -> dict[str, str]:
    return {"widgets": f"{request.base_url}api/widgets/"}


@app.get("/api/widgets/")
def list_widgets() -> list[dict[str, Any]]:
    return [_widget_dict(w) for w in Widget.objects.all()]


def _do_create(raw: bytes) -> Response:
    data, error_response = _parse_body(raw)
    if error_response is not None:
        return error_response

    cleaned, errors = _validate_payload(data, partial=False)
    if errors:
        return JSONResponse(errors, status_code=400)

    widget = Widget.objects.create(name=cleaned["name"], quantity=cleaned["quantity"])
    return JSONResponse(_widget_dict(widget), status_code=201)


@app.post("/api/widgets/")
async def create_widget(request: Request) -> Response:
    raw = await request.body()
    return await run_in_threadpool(_do_create, raw)


@app.get("/api/widgets/{pk}/")
def retrieve_widget(pk: str) -> Response:
    lookup = _lookup_widget(pk)
    if lookup.error is not None:
        return lookup.error
    return JSONResponse(_widget_dict(lookup.widget))


def _do_update(pk: str, raw: bytes) -> Response:
    lookup = _lookup_widget(pk)
    if lookup.error is not None:
        return lookup.error

    data, error_response = _parse_body(raw)
    if error_response is not None:
        return error_response

    cleaned, errors = _validate_payload(data, partial=False)
    if errors:
        return JSONResponse(errors, status_code=400)

    widget = lookup.widget
    widget.name = cleaned["name"]
    widget.quantity = cleaned["quantity"]
    widget.save()
    return JSONResponse(_widget_dict(widget))


@app.put("/api/widgets/{pk}/")
async def update_widget(pk: str, request: Request) -> Response:
    raw = await request.body()
    return await run_in_threadpool(_do_update, pk, raw)


def _do_partial_update(pk: str, raw: bytes) -> Response:
    lookup = _lookup_widget(pk)
    if lookup.error is not None:
        return lookup.error

    data, error_response = _parse_body(raw)
    if error_response is not None:
        return error_response

    cleaned, errors = _validate_payload(data, partial=True)
    if errors:
        return JSONResponse(errors, status_code=400)

    widget = lookup.widget
    for field, value in cleaned.items():
        setattr(widget, field, value)
    if cleaned:
        widget.save()
    return JSONResponse(_widget_dict(widget))


@app.patch("/api/widgets/{pk}/")
async def partial_update_widget(pk: str, request: Request) -> Response:
    raw = await request.body()
    return await run_in_threadpool(_do_partial_update, pk, raw)


@app.delete("/api/widgets/{pk}/")
def delete_widget(pk: str) -> Response:
    lookup = _lookup_widget(pk)
    if lookup.error is not None:
        return lookup.error
    lookup.widget.delete()
    return Response(status_code=204)
