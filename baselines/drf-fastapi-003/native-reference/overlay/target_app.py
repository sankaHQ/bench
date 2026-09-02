from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any

# The serving process owns its configuration: Django keeps only the ORM half.
os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from django.db import transaction  # noqa: E402
from orders.models import Order, OrderItem  # noqa: E402

ALLOW_COLLECTION = "GET, POST, HEAD, OPTIONS"
ALLOW_DETAIL = "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"
STATUS_CHOICES = ("new", "paid", "cancelled")

app = FastAPI(title="Native FastAPI order service")


def _price_repr(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _serialize_item(item: OrderItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "sku": item.sku,
        "quantity": item.quantity,
        "price": _price_repr(item.price),
    }


def _serialize(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "reference": order.reference,
        "status": order.status,
        "memo": order.memo,
        "items": [_serialize_item(item) for item in order.items.order_by("id")],
    }


def _clean_char(value: Any, *, max_length: int, allow_blank: bool) -> tuple[Any, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if value == "" or (isinstance(value, str) and not value.strip()):
        if allow_blank:
            return "", []
        return None, ["This field may not be blank."]
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None, ["Not a valid string."]
    cleaned = str(value).strip()
    if len(cleaned) > max_length:
        return None, [f"Ensure this field has no more than {max_length} characters."]
    return cleaned, []


def _clean_quantity(value: Any) -> tuple[Any, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if isinstance(value, str) and len(value) > 1000:
        return None, ["String value too large."]
    import re

    try:
        cleaned = int(re.sub(r"\.0*\s*$", "", str(value).strip()))
    except (TypeError, ValueError):
        return None, ["A valid integer is required."]
    if cleaned < 1:
        return None, ["Ensure this value is greater than or equal to 1."]
    return cleaned, []


def _clean_price(value: Any) -> tuple[Any, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if isinstance(value, bool):
        return None, ["A valid number is required."]
    try:
        cleaned = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None, ["A valid number is required."]
    if cleaned.is_nan() or cleaned.is_infinite():
        return None, ["A valid number is required."]
    _sign, digittuple, exponent = cleaned.as_tuple()
    if not isinstance(exponent, int):
        return None, ["A valid number is required."]
    if exponent >= 0:
        digits = len(digittuple) + exponent
        decimals = 0
    elif abs(exponent) > len(digittuple):
        digits = decimals = abs(exponent)
    else:
        digits = len(digittuple)
        decimals = abs(exponent)
    whole_digits = digits - decimals
    if digits > 8:
        return None, ["Ensure that there are no more than 8 digits in total."]
    if decimals > 2:
        return None, ["Ensure that there are no more than 2 decimal places."]
    if whole_digits > 6:
        return None, ["Ensure that there are no more than 6 digits before the decimal point."]
    return cleaned, []


def _validate_item(payload: Any) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if not isinstance(payload, dict):
        type_name = type(payload).__name__
        return {}, {
            "non_field_errors": [f"Invalid data. Expected a dictionary, but got {type_name}."]
        }
    errors: dict[str, list[str]] = {}
    validated: dict[str, Any] = {}
    if "sku" not in payload:
        errors["sku"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_char(payload["sku"], max_length=30, allow_blank=False)
        if field_errors:
            errors["sku"] = field_errors
        else:
            validated["sku"] = cleaned
    if "quantity" not in payload:
        errors["quantity"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_quantity(payload["quantity"])
        if field_errors:
            errors["quantity"] = field_errors
        else:
            validated["quantity"] = cleaned
    if "price" not in payload:
        errors["price"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_price(payload["price"])
        if field_errors:
            errors["price"] = field_errors
        else:
            validated["price"] = cleaned
    return validated, errors


def _validate(
    payload: Any, *, partial: bool, current: Order | None
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict):
        type_name = type(payload).__name__
        message = f"Invalid data. Expected a dictionary, but got {type_name}."
        return {}, [], {"non_field_errors": [message]}
    errors: dict[str, Any] = {}
    validated: dict[str, Any] = {}
    items: list[dict[str, Any]] = []

    if "reference" not in payload:
        if not partial:
            errors["reference"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_char(payload["reference"], max_length=30, allow_blank=False)
        if field_errors:
            errors["reference"] = field_errors
        else:
            existing = Order.objects.filter(reference=cleaned)
            if current is not None:
                existing = existing.exclude(pk=current.pk)
            if existing.exists():
                errors["reference"] = ["order with this reference already exists."]
            else:
                validated["reference"] = cleaned

    if "status" in payload:
        value = payload["status"]
        if value not in STATUS_CHOICES:
            errors["status"] = [f'"{value}" is not a valid choice.']
        else:
            validated["status"] = value

    if "memo" in payload:
        cleaned, field_errors = _clean_char(payload["memo"], max_length=200, allow_blank=True)
        if field_errors:
            errors["memo"] = field_errors
        else:
            validated["memo"] = cleaned

    if "items" not in payload:
        if not partial:
            errors["items"] = ["This field is required."]
    else:
        raw_items = payload["items"]
        if not isinstance(raw_items, list):
            type_name = type(raw_items).__name__
            errors["items"] = {
                "non_field_errors": [f'Expected a list of items but got type "{type_name}".']
            }
        else:
            item_errors: dict[str, dict[str, list[str]]] = {}
            for index, raw_item in enumerate(raw_items):
                cleaned_item, one_errors = _validate_item(raw_item)
                if one_errors:
                    item_errors[str(index)] = one_errors
                else:
                    items.append(cleaned_item)
            if item_errors:
                errors["items"] = item_errors
    return validated, items, errors


async def _read_raw_body(request: Request) -> bytes:
    return await request.body()


def _parse_json(raw: bytes, allow: str) -> tuple[Any, Response | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, JSONResponse(
            {"detail": f"JSON parse error - {exc}"}, status_code=400, headers={"Allow": allow}
        )


def _not_found(allow: str, cause: str) -> Response:
    detail = "No Order matches the given query." if cause == "missing" else "Not found."
    return JSONResponse({"detail": detail}, status_code=404, headers={"Allow": allow})


def _get_order(request: Request) -> tuple[Order | None, str]:
    raw = request.path_params.get("pk")
    try:
        return Order.objects.get(pk=raw), ""
    except Order.DoesNotExist:
        return None, "missing"
    except (TypeError, ValueError, OverflowError):
        return None, "invalid"


@app.get("/api/orders/")
def list_orders(request: Request) -> Response:
    payload = [_serialize(order) for order in Order.objects.order_by("id")]
    return JSONResponse(payload, headers={"Allow": ALLOW_COLLECTION})


@app.post("/api/orders/")
def create_order(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    payload, parse_error = _parse_json(raw_body, ALLOW_COLLECTION)
    if parse_error is not None:
        return parse_error
    validated, items, errors = _validate(payload, partial=False, current=None)
    if errors:
        return JSONResponse(errors, status_code=400, headers={"Allow": ALLOW_COLLECTION})
    total = sum(item["quantity"] for item in items)
    if total > 100:
        return JSONResponse(
            {"items": ["Order exceeds 100 total units."]},
            status_code=400,
            headers={"Allow": ALLOW_COLLECTION},
        )
    with transaction.atomic():
        order = Order.objects.create(**validated)
        for item in items:
            OrderItem.objects.create(order=order, **item)
    return JSONResponse(_serialize(order), status_code=201, headers={"Allow": ALLOW_COLLECTION})


@app.get("/api/orders/{pk}/")
def retrieve_order(request: Request) -> Response:
    order, miss = _get_order(request)
    if order is None:
        return _not_found(ALLOW_DETAIL, miss)
    return JSONResponse(_serialize(order), headers={"Allow": ALLOW_DETAIL})


def _mutate(request: Request, raw_body: bytes, *, partial: bool) -> Response:
    order, miss = _get_order(request)
    if order is None:
        return _not_found(ALLOW_DETAIL, miss)
    payload, parse_error = _parse_json(raw_body, ALLOW_DETAIL)
    if parse_error is not None:
        return parse_error
    validated, _, errors = _validate(payload, partial=partial, current=order)
    if errors:
        return JSONResponse(errors, status_code=400, headers={"Allow": ALLOW_DETAIL})
    for name, value in validated.items():
        setattr(order, name, value)
    order.save()
    return JSONResponse(_serialize(order), headers={"Allow": ALLOW_DETAIL})


@app.put("/api/orders/{pk}/")
def update_order(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    return _mutate(request, raw_body, partial=False)


@app.patch("/api/orders/{pk}/")
def partial_update_order(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    return _mutate(request, raw_body, partial=True)


@app.delete("/api/orders/{pk}/")
def destroy_order(request: Request) -> Response:
    order, miss = _get_order(request)
    if order is None:
        return _not_found(ALLOW_DETAIL, miss)
    order.delete()
    return Response(status_code=204, headers={"Allow": ALLOW_DETAIL})
