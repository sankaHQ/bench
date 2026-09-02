"""Native FastAPI serving app for the orders API.

Django is kept for the ORM only. This module points Django at
shop_config.serving_settings (rest_framework stripped out of
INSTALLED_APPS) and never imports rest_framework or Django's
request-serving machinery (django.core.asgi/wsgi/handlers, django.test).
"""

import os
from decimal import Decimal, InvalidOperation

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shop_config.serving_settings")

import django

django.setup()

from django.db import transaction
from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse, Response

from orders.models import Order, OrderItem

app = FastAPI()

STATUS_CHOICES = {"new", "paid", "cancelled"}


class DRFValidationError(Exception):
    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


def validate_char(data, field, max_length, required, allow_blank, default=None):
    if field not in data:
        if required:
            raise DRFValidationError(["This field is required."])
        return default
    value = data[field]
    if value is None:
        raise DRFValidationError(["This field may not be null."])
    if not isinstance(value, str):
        raise DRFValidationError(["Not a valid string."])
    if value == "" and not allow_blank:
        raise DRFValidationError(["This field may not be blank."])
    if max_length is not None and len(value) > max_length:
        raise DRFValidationError(
            [f"Ensure this field has no more than {max_length} characters."]
        )
    return value


def validate_choice(data, field, choices, required, default=None):
    if field not in data:
        if required:
            raise DRFValidationError(["This field is required."])
        return default
    value = data[field]
    if value is None:
        raise DRFValidationError(["This field may not be null."])
    if value not in choices:
        raise DRFValidationError([f'"{value}" is not a valid choice.'])
    return value


def validate_integer(data, field, required, min_value=None, default=None):
    if field not in data:
        if required:
            raise DRFValidationError(["This field is required."])
        return default
    value = data[field]
    if value is None:
        raise DRFValidationError(["This field may not be null."])
    if isinstance(value, bool):
        raise DRFValidationError(["A valid integer is required."])
    try:
        ivalue = int(str(value))
    except (ValueError, TypeError):
        raise DRFValidationError(["A valid integer is required."])
    if min_value is not None and ivalue < min_value:
        raise DRFValidationError(
            [f"Ensure this value is greater than or equal to {min_value}."]
        )
    return ivalue


def validate_decimal(data, field, required, max_digits, decimal_places, default=None):
    if field not in data:
        if required:
            raise DRFValidationError(["This field is required."])
        return default
    raw = data[field]
    if raw is None:
        raise DRFValidationError(["This field may not be null."])
    if isinstance(raw, bool):
        raise DRFValidationError(["A valid number is required."])
    try:
        text = str(raw).strip()
        value = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        raise DRFValidationError(["A valid number is required."])
    if value.is_nan() or value in (Decimal("Inf"), Decimal("-Inf")):
        raise DRFValidationError(["A valid number is required."])

    sign, digits, exponent = value.as_tuple()
    if exponent >= 0:
        total_digits = len(digits) + exponent
        whole_digits = total_digits
        decimals = 0
    elif len(digits) > abs(exponent):
        total_digits = len(digits)
        whole_digits = total_digits - abs(exponent)
        decimals = abs(exponent)
    else:
        total_digits = abs(exponent)
        whole_digits = 0
        decimals = total_digits

    if total_digits > max_digits:
        raise DRFValidationError(
            [f"Ensure that there are no more than {max_digits} digits in total."]
        )
    if decimals > decimal_places:
        raise DRFValidationError(
            [f"Ensure that there are no more than {decimal_places} decimal places."]
        )
    if whole_digits > (max_digits - decimal_places):
        raise DRFValidationError(
            [
                "Ensure that there are no more than "
                f"{max_digits - decimal_places} digits before the decimal point."
            ]
        )
    return value


def validate_item(item):
    if not isinstance(item, dict):
        raise DRFValidationError(
            {
                "non_field_errors": [
                    f"Invalid data. Expected a dictionary, but got {type(item).__name__}."
                ]
            }
        )
    errors = {}
    values = {}
    try:
        values["sku"] = validate_char(item, "sku", 30, required=True, allow_blank=False)
    except DRFValidationError as exc:
        errors["sku"] = exc.detail
    try:
        values["quantity"] = validate_integer(item, "quantity", required=True, min_value=1)
    except DRFValidationError as exc:
        errors["quantity"] = exc.detail
    try:
        values["price"] = validate_decimal(
            item, "price", required=True, max_digits=8, decimal_places=2
        )
    except DRFValidationError as exc:
        errors["price"] = exc.detail
    if errors:
        raise DRFValidationError(errors)
    return values


def validate_items(data, required):
    if "items" not in data:
        if required:
            raise DRFValidationError(["This field is required."])
        return None
    value = data["items"]
    if not isinstance(value, list):
        raise DRFValidationError(
            {
                "non_field_errors": [
                    f'Expected a list of items but got type "{type(value).__name__}".'
                ]
            }
        )
    results = []
    errors = {}
    for index, item in enumerate(value):
        try:
            results.append(validate_item(item))
        except DRFValidationError as exc:
            errors[index] = exc.detail
    if errors:
        raise DRFValidationError(errors)
    return results


def validate_order(data, partial, instance=None):
    if not isinstance(data, dict):
        raise DRFValidationError(
            {"non_field_errors": [f"Invalid data. Expected a dictionary, but got {type(data).__name__}."]}
        )

    errors = {}
    values = {}

    if not partial or "reference" in data:
        try:
            reference = validate_char(data, "reference", 30, required=True, allow_blank=False)
        except DRFValidationError as exc:
            errors["reference"] = exc.detail
        else:
            qs = Order.objects.filter(reference=reference)
            if instance is not None:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                errors["reference"] = ["order with this reference already exists."]
            else:
                values["reference"] = reference

    if not partial or "status" in data:
        try:
            values["status"] = validate_choice(
                data, "status", STATUS_CHOICES, required=False, default="new"
            )
        except DRFValidationError as exc:
            errors["status"] = exc.detail

    if not partial or "memo" in data:
        try:
            values["memo"] = validate_char(
                data, "memo", 200, required=False, allow_blank=True, default=""
            )
        except DRFValidationError as exc:
            errors["memo"] = exc.detail

    if not partial or "items" in data:
        try:
            values["items"] = validate_items(data, required=True)
        except DRFValidationError as exc:
            errors["items"] = exc.detail

    if errors:
        raise DRFValidationError(errors)
    return values


def quantize_price(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantized = value.quantize(Decimal("1.00"))
    return f"{quantized:f}"


def serialize_item(item):
    return {
        "id": item.id,
        "sku": item.sku,
        "quantity": item.quantity,
        "price": quantize_price(item.price),
    }


def serialize_order(order):
    return {
        "id": order.id,
        "reference": order.reference,
        "status": order.status,
        "memo": order.memo,
        "items": [serialize_item(item) for item in order.items.all().order_by("id")],
    }


def perform_create(values):
    with transaction.atomic():
        order = Order.objects.create(
            reference=values["reference"],
            status=values["status"],
            memo=values["memo"],
        )
        for item in values["items"]:
            OrderItem.objects.create(
                order=order,
                sku=item["sku"],
                quantity=item["quantity"],
                price=item["price"],
            )
        total = sum(item.quantity for item in order.items.all())
        if total > 100:
            raise DRFValidationError({"items": ["Order exceeds 100 total units."]})
    return order


def get_order_or_none(pk):
    try:
        return Order.objects.get(pk=pk)
    except (Order.DoesNotExist, ValueError, TypeError):
        return None


NOT_FOUND_RESPONSE = {"detail": "No Order matches the given query."}


@app.get("/api/orders/")
def list_orders():
    orders = Order.objects.all().order_by("id")
    return JSONResponse([serialize_order(order) for order in orders], status_code=200)


@app.post("/api/orders/")
def create_order(payload: dict = Body(...)):
    try:
        values = validate_order(payload, partial=False)
    except DRFValidationError as exc:
        return JSONResponse(exc.detail, status_code=400)
    try:
        order = perform_create(values)
    except DRFValidationError as exc:
        return JSONResponse(exc.detail, status_code=400)
    return JSONResponse(serialize_order(order), status_code=201)


@app.get("/api/orders/{pk}/")
def retrieve_order(pk: str):
    order = get_order_or_none(pk)
    if order is None:
        return JSONResponse(NOT_FOUND_RESPONSE, status_code=404)
    return JSONResponse(serialize_order(order), status_code=200)


@app.put("/api/orders/{pk}/")
def update_order(pk: str, payload: dict = Body(...)):
    order = get_order_or_none(pk)
    if order is None:
        return JSONResponse(NOT_FOUND_RESPONSE, status_code=404)
    try:
        values = validate_order(payload, partial=False, instance=order)
    except DRFValidationError as exc:
        return JSONResponse(exc.detail, status_code=400)
    values.pop("items", None)
    for field, value in values.items():
        setattr(order, field, value)
    order.save()
    return JSONResponse(serialize_order(order), status_code=200)


@app.patch("/api/orders/{pk}/")
def partial_update_order(pk: str, payload: dict = Body(...)):
    order = get_order_or_none(pk)
    if order is None:
        return JSONResponse(NOT_FOUND_RESPONSE, status_code=404)
    try:
        values = validate_order(payload, partial=True, instance=order)
    except DRFValidationError as exc:
        return JSONResponse(exc.detail, status_code=400)
    values.pop("items", None)
    for field, value in values.items():
        setattr(order, field, value)
    order.save()
    return JSONResponse(serialize_order(order), status_code=200)


@app.delete("/api/orders/{pk}/")
def delete_order(pk: str):
    order = get_order_or_none(pk)
    if order is None:
        return JSONResponse(NOT_FOUND_RESPONSE, status_code=404)
    order.delete()
    return Response(status_code=204)
