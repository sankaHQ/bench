from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any

os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from django.db import transaction
from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse, Response

django.setup()

from orders.models import Order, OrderEvent  # noqa: E402

app = FastAPI(title="Native FastAPI state-machine reference")
REQUEST_BODY = Body(...)
STATUSES = ("draft", "submitted", "approved", "shipped", "cancelled")
LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("submitted", "cancelled"),
    "submitted": ("approved", "cancelled"),
    "approved": ("shipped",),
    "shipped": (),
    "cancelled": (),
}


def _serialize(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "number": order.number,
        "status": order.status,
        "version": order.version,
        "total": format(order.total, ".2f"),
        "notes": order.notes,
        "allowed_transitions": list(LEGAL_TRANSITIONS[order.status]),
    }


def _not_found() -> JSONResponse:
    return JSONResponse(
        {"detail": "No Order matches the given query."},
        status_code=404,
    )


def _get_order(identifier: int, *, locked: bool = False) -> Order | None:
    query = Order.objects.select_for_update() if locked else Order.objects
    return query.filter(pk=identifier).first()


def _conflict(order: Order, provided_version: int) -> JSONResponse:
    return JSONResponse(
        {
            "detail": "Version conflict.",
            "expected_version": order.version,
            "provided_version": provided_version,
        },
        status_code=409,
    )


def _integer(value: Any, field: str) -> tuple[int | None, dict[str, list[str]]]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, {field: ["A valid integer is required."]}
    if parsed < 1:
        return None, {field: ["Ensure this value is greater than or equal to 1."]}
    return parsed, {}


def _decimal(value: Any) -> tuple[Decimal | None, list[str]]:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, ["A valid number is required."]
    if parsed.as_tuple().exponent < -2:
        return None, ["Ensure that there are no more than 2 decimal places."]
    if len(parsed.as_tuple().digits) > 10:
        return None, ["Ensure that there are no more than 10 digits in total."]
    return parsed.quantize(Decimal("0.01")), []


@app.get("/api/orders/")
def list_orders() -> Response:
    return JSONResponse([_serialize(order) for order in Order.objects.order_by("id")])


@app.post("/api/orders/")
def create_order(payload: dict[str, Any] = REQUEST_BODY) -> Response:
    errors: dict[str, list[str]] = {}
    number = payload.get("number")
    if number is None:
        errors["number"] = ["This field is required."]
    elif not str(number).strip():
        errors["number"] = ["This field may not be blank."]
    elif Order.objects.filter(number=str(number).strip()).exists():
        errors["number"] = ["order with this number already exists."]

    if "total" not in payload:
        errors["total"] = ["This field is required."]
        total = None
    else:
        total, total_errors = _decimal(payload["total"])
        if total_errors:
            errors["total"] = total_errors
    if errors:
        return JSONResponse(errors, status_code=400)

    notes = str(payload.get("notes", "")).strip()
    with transaction.atomic():
        order = Order.objects.create(
            number=str(number).strip(),
            total=total,
            notes=notes,
        )
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.CREATED,
            from_status=order.status,
            to_status=order.status,
            version=order.version,
        )
    return JSONResponse(_serialize(order), status_code=201)


@app.get("/api/orders/{identifier}/")
def retrieve_order(identifier: int) -> Response:
    order = _get_order(identifier)
    return JSONResponse(_serialize(order)) if order is not None else _not_found()


@app.patch("/api/orders/{identifier}/")
def patch_order(identifier: int, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    if "version" not in payload:
        return JSONResponse({"version": ["This field is required."]}, status_code=400)
    provided_version, errors = _integer(payload["version"], "version")
    if errors:
        return JSONResponse(errors, status_code=400)
    mutable = {key: value for key, value in payload.items() if key in {"total", "notes"}}
    if not mutable:
        return JSONResponse(
            {"non_field_errors": ["At least one mutable field is required."]},
            status_code=400,
        )
    if "total" in mutable:
        total, total_errors = _decimal(mutable["total"])
        if total_errors:
            return JSONResponse({"total": total_errors}, status_code=400)
        mutable["total"] = total
    if "notes" in mutable:
        mutable["notes"] = str(mutable["notes"]).strip()

    with transaction.atomic():
        order = _get_order(identifier, locked=True)
        if order is None:
            return _not_found()
        assert provided_version is not None
        if order.version != provided_version:
            return _conflict(order, provided_version)
        for field, value in mutable.items():
            setattr(order, field, value)
        order.version += 1
        order.save(update_fields=[*mutable, "version"])
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.UPDATED,
            from_status=order.status,
            to_status=order.status,
            version=order.version,
        )
    return JSONResponse(_serialize(order))


@app.post("/api/orders/{identifier}/transition/")
def transition_order(identifier: int, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    errors: dict[str, list[str]] = {}
    target = payload.get("to_status")
    if target is None:
        errors["to_status"] = ["This field is required."]
    elif target not in STATUSES:
        errors["to_status"] = [f'"{target}" is not a valid choice.']
    if "version" not in payload:
        errors["version"] = ["This field is required."]
        provided_version = None
    else:
        provided_version, version_errors = _integer(payload["version"], "version")
        errors.update(version_errors)
    if errors:
        return JSONResponse(errors, status_code=400)

    with transaction.atomic():
        order = _get_order(identifier, locked=True)
        if order is None:
            return _not_found()
        assert provided_version is not None
        if order.version != provided_version:
            return _conflict(order, provided_version)
        allowed = LEGAL_TRANSITIONS[order.status]
        if target not in allowed:
            return JSONResponse(
                {
                    "detail": f"Transition from {order.status} to {target} is not allowed.",
                    "allowed": list(allowed),
                },
                status_code=409,
            )
        previous = order.status
        order.status = str(target)
        order.version += 1
        order.save(update_fields=["status", "version"])
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.TRANSITIONED,
            from_status=previous,
            to_status=order.status,
            version=order.version,
        )
    return JSONResponse(_serialize(order))
