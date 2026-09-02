from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from django.db import IntegrityError, transaction  # noqa: E402
from orders.models import Adjustment, Order, OrderItem  # noqa: E402

MISSING = object()
INTEGER_TAIL = re.compile(r"\.0*\s*$")

app = FastAPI(title="Native FastAPI deep-order reference")


class NestedWriteError(Exception):
    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(str(detail))
        self.detail = detail


def _decimal_repr(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _serialize_adjustment(adjustment: Adjustment) -> dict[str, Any]:
    return {
        "id": adjustment.id,
        "code": adjustment.code,
        "amount": _decimal_repr(adjustment.amount),
        "note": adjustment.note,
    }


def _serialize_item(item: OrderItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "sku": item.sku,
        "quantity": item.quantity,
        "description": item.description,
        "adjustments": [
            _serialize_adjustment(adjustment) for adjustment in item.adjustments.order_by("id")
        ],
    }


def _serialize(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "reference": order.reference,
        "customer_note": order.customer_note,
        "items": [_serialize_item(item) for item in order.items.order_by("id")],
    }


def _clean_char(
    value: Any,
    *,
    max_length: int,
    allow_blank: bool,
) -> tuple[str | None, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None, ["Not a valid string."]
    cleaned = str(value).strip()
    if not cleaned and not allow_blank:
        return None, ["This field may not be blank."]
    if len(cleaned) > max_length:
        return None, [f"Ensure this field has no more than {max_length} characters."]
    return cleaned, []


def _clean_quantity(value: Any) -> tuple[int | None, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if isinstance(value, bool):
        return None, ["A valid integer is required."]
    try:
        cleaned = int(INTEGER_TAIL.sub("", str(value).strip()))
    except (TypeError, ValueError):
        return None, ["A valid integer is required."]
    if cleaned < 1:
        return None, ["Ensure this value is greater than or equal to 1."]
    return cleaned, []


def _clean_amount(value: Any) -> tuple[Decimal | None, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if isinstance(value, bool):
        return None, ["A valid number is required."]
    try:
        cleaned = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None, ["A valid number is required."]
    if cleaned.is_nan() or cleaned.is_infinite():
        return None, ["A valid number is required."]
    _sign, digits_tuple, exponent = cleaned.as_tuple()
    if not isinstance(exponent, int):
        return None, ["A valid number is required."]
    if exponent >= 0:
        digits = len(digits_tuple) + exponent
        decimals = 0
    elif abs(exponent) > len(digits_tuple):
        digits = decimals = abs(exponent)
    else:
        digits = len(digits_tuple)
        decimals = abs(exponent)
    whole_digits = digits - decimals
    if digits > 8:
        return None, ["Ensure that there are no more than 8 digits in total."]
    if decimals > 2:
        return None, ["Ensure that there are no more than 2 decimal places."]
    if whole_digits > 6:
        return None, ["Ensure that there are no more than 6 digits before the decimal point."]
    return cleaned, []


def _invalid_mapping(value: Any) -> dict[str, list[str]]:
    kind = type(value).__name__
    return {"non_field_errors": [f"Invalid data. Expected a dictionary, but got {kind}."]}


def _validate_adjustment(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}, _invalid_mapping(payload)
    validated: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    if "code" not in payload:
        errors["code"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_char(payload["code"], max_length=20, allow_blank=False)
        if field_errors:
            errors["code"] = field_errors
        else:
            validated["code"] = cleaned
    if "amount" not in payload:
        errors["amount"] = ["This field is required."]
    else:
        amount, field_errors = _clean_amount(payload["amount"])
        if field_errors:
            errors["amount"] = field_errors
        else:
            validated["amount"] = amount
    if "note" in payload:
        cleaned, field_errors = _clean_char(payload["note"], max_length=100, allow_blank=True)
        if field_errors:
            errors["note"] = field_errors
        else:
            validated["note"] = cleaned
    return validated, errors


def _validate_item(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}, _invalid_mapping(payload)
    validated: dict[str, Any] = {}
    errors: dict[str, Any] = {}
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
        quantity, field_errors = _clean_quantity(payload["quantity"])
        if field_errors:
            errors["quantity"] = field_errors
        else:
            validated["quantity"] = quantity
    if "description" in payload:
        cleaned, field_errors = _clean_char(
            payload["description"], max_length=120, allow_blank=True
        )
        if field_errors:
            errors["description"] = field_errors
        else:
            validated["description"] = cleaned
    if "adjustments" not in payload:
        errors["adjustments"] = ["This field is required."]
    else:
        raw_adjustments = payload["adjustments"]
        if raw_adjustments is None:
            errors["adjustments"] = ["This field may not be null."]
        elif not isinstance(raw_adjustments, list):
            kind = type(raw_adjustments).__name__
            errors["adjustments"] = {
                "non_field_errors": [f'Expected a list of items but got type "{kind}".']
            }
        else:
            adjustment_errors: dict[str, Any] = {}
            adjustments: list[dict[str, Any]] = []
            for index, raw_adjustment in enumerate(raw_adjustments):
                adjustment, one_errors = _validate_adjustment(raw_adjustment)
                if one_errors:
                    adjustment_errors[str(index)] = one_errors
                else:
                    adjustments.append(adjustment)
            if adjustment_errors:
                errors["adjustments"] = adjustment_errors
            else:
                validated["adjustments"] = adjustments
    return validated, errors


def _validate(
    payload: Any,
    *,
    partial: bool,
    current: Order | None,
) -> tuple[dict[str, Any], object | list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}, MISSING, _invalid_mapping(payload)
    validated: dict[str, Any] = {}
    errors: dict[str, Any] = {}

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

    if "customer_note" in payload:
        cleaned, field_errors = _clean_char(
            payload["customer_note"], max_length=200, allow_blank=True
        )
        if field_errors:
            errors["customer_note"] = field_errors
        else:
            validated["customer_note"] = cleaned

    items: object | list[dict[str, Any]] = MISSING
    if "items" not in payload:
        if not partial:
            errors["items"] = ["This field is required."]
    else:
        raw_items = payload["items"]
        if raw_items is None:
            errors["items"] = ["This field may not be null."]
        elif not isinstance(raw_items, list):
            kind = type(raw_items).__name__
            errors["items"] = {
                "non_field_errors": [f'Expected a list of items but got type "{kind}".']
            }
        else:
            item_errors: dict[str, Any] = {}
            cleaned_items: list[dict[str, Any]] = []
            for index, raw_item in enumerate(raw_items):
                item, one_errors = _validate_item(raw_item)
                if one_errors:
                    item_errors[str(index)] = one_errors
                else:
                    cleaned_items.append(item)
            if item_errors:
                errors["items"] = item_errors
            else:
                items = cleaned_items
    return validated, items, errors


def _create_items(order: Order, items: list[dict[str, Any]]) -> None:
    for item_index, item_data in enumerate(items):
        data = dict(item_data)
        adjustments = data.pop("adjustments")
        try:
            item = OrderItem.objects.create(order=order, **data)
        except IntegrityError as exc:
            raise NestedWriteError(
                {
                    "items": {
                        str(item_index): {
                            "non_field_errors": ["The fields order, sku must make a unique set."]
                        }
                    }
                }
            ) from exc
        for adjustment_index, adjustment in enumerate(adjustments):
            try:
                Adjustment.objects.create(item=item, **adjustment)
            except IntegrityError as exc:
                raise NestedWriteError(
                    {
                        "items": {
                            str(item_index): {
                                "adjustments": {
                                    str(adjustment_index): {
                                        "non_field_errors": [
                                            "The fields item, code must make a unique set."
                                        ]
                                    }
                                }
                            }
                        }
                    }
                ) from exc


async def _raw_body(request: Request) -> bytes:
    return await request.body()


def _parse_json(raw: bytes) -> tuple[Any, Response | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, JSONResponse(
            {"detail": f"JSON parse error - {exc}"},
            status_code=400,
        )


def _find_order(pk: str) -> Order | None:
    try:
        return Order.objects.get(pk=pk)
    except (Order.DoesNotExist, TypeError, ValueError, OverflowError):
        return None


def _not_found() -> Response:
    return JSONResponse({"detail": "No Order matches the given query."}, status_code=404)


@app.get("/api/")
def api_root() -> Response:
    return JSONResponse({"orders": "http://testserver/api/orders/"})


@app.get("/api/orders/")
def list_orders() -> Response:
    return JSONResponse([_serialize(order) for order in Order.objects.order_by("id")])


@app.post("/api/orders/")
def create_order(raw: bytes = Depends(_raw_body)) -> Response:
    payload, parse_error = _parse_json(raw)
    if parse_error is not None:
        return parse_error
    validated, items, errors = _validate(payload, partial=False, current=None)
    if errors:
        return JSONResponse(errors, status_code=400)
    assert isinstance(items, list)
    try:
        with transaction.atomic():
            order = Order.objects.create(**validated)
            _create_items(order, items)
    except NestedWriteError as exc:
        return JSONResponse(exc.detail, status_code=400)
    return JSONResponse(_serialize(order), status_code=201)


@app.get("/api/orders/{pk}/")
def retrieve_order(pk: str) -> Response:
    order = _find_order(pk)
    if order is None:
        return _not_found()
    return JSONResponse(_serialize(order))


def _update(pk: str, raw: bytes, *, partial: bool) -> Response:
    order = _find_order(pk)
    if order is None:
        return _not_found()
    payload, parse_error = _parse_json(raw)
    if parse_error is not None:
        return parse_error
    validated, items, errors = _validate(payload, partial=partial, current=order)
    if errors:
        return JSONResponse(errors, status_code=400)
    try:
        with transaction.atomic():
            for name, value in validated.items():
                setattr(order, name, value)
            order.save()
            if items is not MISSING:
                assert isinstance(items, list)
                order.items.all().delete()
                _create_items(order, items)
    except NestedWriteError as exc:
        return JSONResponse(exc.detail, status_code=400)
    return JSONResponse(_serialize(order))


@app.put("/api/orders/{pk}/")
def update_order(pk: str, raw: bytes = Depends(_raw_body)) -> Response:
    return _update(pk, raw, partial=False)


@app.patch("/api/orders/{pk}/")
def partial_update_order(pk: str, raw: bytes = Depends(_raw_body)) -> Response:
    return _update(pk, raw, partial=True)


@app.delete("/api/orders/{pk}/")
def destroy_order(pk: str) -> Response:
    order = _find_order(pk)
    if order is None:
        return _not_found()
    order.delete()
    return Response(status_code=204)
