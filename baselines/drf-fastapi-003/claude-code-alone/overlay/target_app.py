"""Native FastAPI serving app for the orders API.

Django is used strictly for the ORM (models + migrations state). The
serving settings module (shop_config.serving_settings) strips
rest_framework out of INSTALLED_APPS, and this module never imports
rest_framework or any Django request-serving machinery.
"""
from __future__ import annotations

import decimal
import os
import re

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shop_config.serving_settings")

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402

from orders.models import Order, OrderItem  # noqa: E402

from fastapi import Body, FastAPI, Response  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

app = FastAPI()

STATUS_CHOICES = {"new", "paid", "cancelled"}
REFERENCE_MAX_LENGTH = 30
MEMO_MAX_LENGTH = 200
SKU_MAX_LENGTH = 30
PRICE_MAX_DIGITS = 8
PRICE_DECIMAL_PLACES = 2


class BusinessRuleError(Exception):
    def __init__(self, errors):
        super().__init__(errors)
        self.errors = errors


def not_found_response():
    return JSONResponse(status_code=404, content={"detail": "No Order matches the given query."})


def validate_char_field(value, max_length, allow_blank):
    """Mirrors rest_framework.fields.CharField validation/coercion."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return (["Not a valid string."], None)

    is_blank = value == "" or (isinstance(value, str) and value.strip() == "")
    if is_blank:
        if not allow_blank:
            return (["This field may not be blank."], None)
        return (None, "")

    cleaned = str(value).strip()
    if len(cleaned) > max_length:
        return ([f"Ensure this field has no more than {max_length} characters."], None)
    return (None, cleaned)


def validate_choice_field(value, choices):
    if str(value) in choices:
        return (None, str(value))
    return ([f'"{value}" is not a valid choice.'], None)


_TRAILING_ZERO_DECIMAL = re.compile(r"\.0*\s*$")


def validate_integer_field(value, min_value=None):
    try:
        cleaned = int(_TRAILING_ZERO_DECIMAL.sub("", str(value)))
    except (TypeError, ValueError):
        return (["A valid integer is required."], None)
    if min_value is not None and cleaned < min_value:
        return ([f"Ensure this value is greater than or equal to {min_value}."], None)
    return (None, cleaned)


def validate_decimal_field(value, max_digits, decimal_places):
    text = str(value).strip()
    try:
        parsed = decimal.Decimal(text)
    except decimal.InvalidOperation:
        return (["A valid number is required."], None)
    if parsed.is_nan() or parsed in (decimal.Decimal("Inf"), decimal.Decimal("-Inf")):
        return (["A valid number is required."], None)

    sign, digittuple, exponent = parsed.as_tuple()
    if exponent >= 0:
        total_digits = len(digittuple) + exponent
        whole_digits = total_digits
        places = 0
    elif len(digittuple) > abs(exponent):
        total_digits = len(digittuple)
        whole_digits = total_digits - abs(exponent)
        places = abs(exponent)
    else:
        total_digits = abs(exponent)
        whole_digits = 0
        places = total_digits

    if total_digits > max_digits:
        return ([f"Ensure that there are no more than {max_digits} digits in total."], None)
    if places > decimal_places:
        return ([f"Ensure that there are no more than {decimal_places} decimal places."], None)
    max_whole_digits = max_digits - decimal_places
    if whole_digits > max_whole_digits:
        return (
            [f"Ensure that there are no more than {max_whole_digits} digits before the decimal point."],
            None,
        )

    quantized = parsed.quantize(decimal.Decimal(1).scaleb(-decimal_places))
    return (None, quantized)


def validate_item(data):
    if not isinstance(data, dict):
        return (
            {"non_field_errors": [f"Invalid data. Expected a dictionary, but got {type(data).__name__}."]},
            None,
        )

    errors = {}
    cleaned = {}

    if "sku" not in data:
        errors["sku"] = ["This field is required."]
    else:
        err, val = validate_char_field(data["sku"], SKU_MAX_LENGTH, allow_blank=False)
        if err:
            errors["sku"] = err
        else:
            cleaned["sku"] = val

    if "quantity" not in data:
        errors["quantity"] = ["This field is required."]
    else:
        err, val = validate_integer_field(data["quantity"], min_value=1)
        if err:
            errors["quantity"] = err
        else:
            cleaned["quantity"] = val

    if "price" not in data:
        errors["price"] = ["This field is required."]
    else:
        err, val = validate_decimal_field(data["price"], PRICE_MAX_DIGITS, PRICE_DECIMAL_PLACES)
        if err:
            errors["price"] = err
        else:
            cleaned["price"] = val

    if errors:
        return (errors, None)
    return (None, cleaned)


def validate_items_field(items_raw):
    """Returns (errors, cleaned_list). errors is None on success."""
    if not isinstance(items_raw, list):
        return (
            {"non_field_errors": [f'Expected a list of items but got type "{type(items_raw).__name__}".']},
            None,
        )

    item_errors = {}
    cleaned_items = []
    for index, raw_item in enumerate(items_raw):
        err, cleaned = validate_item(raw_item)
        if err:
            item_errors[index] = err
        else:
            cleaned_items.append(cleaned)

    if item_errors:
        return (item_errors, None)
    return (None, cleaned_items)


def format_price(value: decimal.Decimal) -> str:
    quantized = value.quantize(decimal.Decimal(1).scaleb(-PRICE_DECIMAL_PLACES))
    return f"{quantized:f}"


def serialize_order(order: Order) -> dict:
    return {
        "id": order.id,
        "reference": order.reference,
        "status": order.status,
        "memo": order.memo,
        "items": [
            {
                "id": item.id,
                "sku": item.sku,
                "quantity": item.quantity,
                "price": format_price(item.price),
            }
            for item in order.items.all().order_by("id")
        ],
    }


@app.get("/api/orders/")
def list_orders():
    orders = Order.objects.all().order_by("id")
    return [serialize_order(order) for order in orders]


@app.get("/api/orders/{order_id}/")
def retrieve_order(order_id: int):
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return not_found_response()
    return serialize_order(order)


@app.post("/api/orders/")
def create_order(payload: dict = Body(default={})):
    errors = {}
    cleaned = {}

    if "reference" not in payload:
        errors["reference"] = ["This field is required."]
    else:
        err, val = validate_char_field(payload["reference"], REFERENCE_MAX_LENGTH, allow_blank=False)
        if err:
            errors["reference"] = err
        elif Order.objects.filter(reference=val).exists():
            errors["reference"] = ["order with this reference already exists."]
        else:
            cleaned["reference"] = val

    if "status" in payload:
        err, val = validate_choice_field(payload["status"], STATUS_CHOICES)
        if err:
            errors["status"] = err
        else:
            cleaned["status"] = val
    else:
        cleaned["status"] = "new"

    if "memo" in payload:
        err, val = validate_char_field(payload["memo"], MEMO_MAX_LENGTH, allow_blank=True)
        if err:
            errors["memo"] = err
        else:
            cleaned["memo"] = val
    else:
        cleaned["memo"] = ""

    if "items" not in payload:
        errors["items"] = ["This field is required."]
    else:
        err, val = validate_items_field(payload["items"])
        if err:
            errors["items"] = err
        else:
            cleaned["items"] = val

    if errors:
        return JSONResponse(status_code=400, content=errors)

    try:
        with transaction.atomic():
            order = Order.objects.create(
                reference=cleaned["reference"],
                status=cleaned["status"],
                memo=cleaned["memo"],
            )
            for item in cleaned["items"]:
                OrderItem.objects.create(order=order, **item)
            total = sum(i.quantity for i in order.items.all())
            if total > 100:
                raise BusinessRuleError({"items": ["Order exceeds 100 total units."]})
    except BusinessRuleError as exc:
        return JSONResponse(status_code=400, content=exc.errors)

    return JSONResponse(status_code=201, content=serialize_order(order))


def _apply_partial_update(order: Order, payload: dict):
    """Validates and applies a partial update, mirroring OrderSerializer.update
    (which always drops "items" from validated_data)."""
    errors = {}
    updates = {}

    if "reference" in payload:
        err, val = validate_char_field(payload["reference"], REFERENCE_MAX_LENGTH, allow_blank=False)
        if err:
            errors["reference"] = err
        elif Order.objects.filter(reference=val).exclude(pk=order.pk).exists():
            errors["reference"] = ["order with this reference already exists."]
        else:
            updates["reference"] = val

    if "status" in payload:
        err, val = validate_choice_field(payload["status"], STATUS_CHOICES)
        if err:
            errors["status"] = err
        else:
            updates["status"] = val

    if "memo" in payload:
        err, val = validate_char_field(payload["memo"], MEMO_MAX_LENGTH, allow_blank=True)
        if err:
            errors["memo"] = err
        else:
            updates["memo"] = val

    if "items" in payload:
        err, _val = validate_items_field(payload["items"])
        if err:
            errors["items"] = err

    return errors, updates


@app.patch("/api/orders/{order_id}/")
def partial_update_order(order_id: int, payload: dict = Body(default={})):
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return not_found_response()

    errors, updates = _apply_partial_update(order, payload)
    if errors:
        return JSONResponse(status_code=400, content=errors)

    for field, value in updates.items():
        setattr(order, field, value)
    order.save()

    return serialize_order(order)


@app.put("/api/orders/{order_id}/")
def update_order(order_id: int, payload: dict = Body(default={})):
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return not_found_response()

    errors = {}

    if "reference" not in payload:
        errors["reference"] = ["This field is required."]
    if "items" not in payload:
        errors["items"] = ["This field is required."]

    sub_errors, updates = _apply_partial_update(order, payload)
    errors.update(sub_errors)

    if errors:
        return JSONResponse(status_code=400, content=errors)

    if "status" not in payload:
        updates.setdefault("status", "new")
    if "memo" not in payload:
        updates.setdefault("memo", "")

    for field, value in updates.items():
        setattr(order, field, value)
    order.save()

    return serialize_order(order)


@app.delete("/api/orders/{order_id}/")
def delete_order(order_id: int):
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return not_found_response()
    order.delete()
    return Response(status_code=204)
