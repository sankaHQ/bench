from __future__ import annotations

import os
from typing import Annotated, Any

# The serving process owns its configuration: point Django at the DRF-free
# settings so only the ORM half of the source application is loaded.
os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse, Response

django.setup()

from widgets.models import Widget  # noqa: E402

app = FastAPI(title="Native FastAPI widget service")


def _serialize(widget: Widget) -> dict[str, Any]:
    return {"id": widget.id, "name": widget.name, "quantity": widget.quantity}


def _validate(payload: dict[str, Any], *, partial: bool = False) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    if not partial and "name" not in payload:
        errors["name"] = ["This field is required."]
    elif "name" in payload and payload["name"] == "":
        errors["name"] = ["This field may not be blank."]
    if not partial and "quantity" not in payload:
        errors["quantity"] = ["This field is required."]
    elif "quantity" in payload:
        quantity = payload["quantity"]
        if not isinstance(quantity, int):
            errors["quantity"] = ["A valid integer is required."]
        elif quantity < 0:
            errors["quantity"] = ["Ensure this value is greater than or equal to 0."]
    return errors


@app.get("/api/widgets/")
def list_widgets() -> list[dict[str, Any]]:
    return [_serialize(widget) for widget in Widget.objects.order_by("id")]


@app.post("/api/widgets/")
def create_widget(payload: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    errors = _validate(payload)
    if errors:
        return JSONResponse(errors, status_code=400)
    widget = Widget.objects.create(name=payload["name"], quantity=payload["quantity"])
    return JSONResponse(_serialize(widget), status_code=201)


@app.patch("/api/widgets/{widget_id}/")
def update_widget(widget_id: int, payload: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    try:
        widget = Widget.objects.get(id=widget_id)
    except Widget.DoesNotExist:
        return JSONResponse({"detail": "No Widget matches the given query."}, status_code=404)
    errors = _validate(payload, partial=True)
    if errors:
        return JSONResponse(errors, status_code=400)
    if "name" in payload:
        widget.name = payload["name"]
    if "quantity" in payload:
        widget.quantity = payload["quantity"]
    widget.save(update_fields=["name", "quantity"])
    return JSONResponse(_serialize(widget))


@app.delete("/api/widgets/{widget_id}/", status_code=204)
def delete_widget(widget_id: int) -> Response:
    Widget.objects.filter(id=widget_id).delete()
    return Response(status_code=204)
