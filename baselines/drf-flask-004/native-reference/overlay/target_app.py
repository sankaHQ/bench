from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from flask import Flask, jsonify, request

django.setup()

from wallets.models import Wallet  # noqa: E402
from wallets.services import transfer_money  # noqa: E402

app = Flask(__name__)


def _tenant():
    header = request.headers.get("Authorization")
    tenant = {"ApiKey north-key": "north", "ApiKey south-key": "south"}.get(header)
    if tenant:
        return tenant, None
    detail = (
        "Authentication credentials were not provided." if header is None else "Invalid tenant key."
    )
    return None, (jsonify({"detail": detail}), 401, {"WWW-Authenticate": 'ApiKey realm="wallets"'})


def _amount(value):
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None, "A valid number is required."
    if not number.is_finite():
        return None, "A valid number is required."
    _, digits, exponent = number.as_tuple()
    total_digits = len(digits) + max(exponent, 0)
    decimal_places = max(-exponent, 0)
    total_digits = max(total_digits, decimal_places)
    if total_digits > 9:
        return None, "Ensure that there are no more than 9 digits in total."
    if decimal_places > 2:
        return None, "Ensure that there are no more than 2 decimal places."
    if total_digits - decimal_places > 7:
        return None, "Ensure that there are no more than 7 digits before the decimal point."
    if number < Decimal("0.01"):
        return None, "Ensure this value is greater than or equal to 0.01."
    return number.quantize(Decimal("0.01")), None


def _validate(payload):
    values = {}
    errors = {}
    for field in ("source", "destination", "amount", "idempotency_key"):
        if field not in payload:
            errors[field] = ["This field is required."]
            continue
        value = payload[field]
        if value is None:
            errors[field] = ["This field may not be null."]
            continue
        if field in {"source", "destination"}:
            try:
                number = int(str(value).removesuffix(".0"))
            except ValueError:
                errors[field] = ["A valid integer is required."]
                continue
            if number < 1:
                errors[field] = ["Ensure this value is greater than or equal to 1."]
            else:
                values[field] = number
        elif field == "amount":
            amount, error = _amount(value)
            if error:
                errors[field] = [error]
            else:
                values[field] = amount
        else:
            if isinstance(value, bool) or not isinstance(value, str | int | float):
                errors[field] = ["Not a valid string."]
                continue
            value = str(value).strip()
            if not value:
                errors[field] = ["This field may not be blank."]
            elif len(value) > 40:
                errors[field] = ["Ensure this field has no more than 40 characters."]
            else:
                values[field] = value
    if not errors and values["source"] == values["destination"]:
        errors["non_field_errors"] = ["Source and destination must differ."]
    return values, errors


@app.get("/api/wallets/")
def list_wallets():
    tenant, failure = _tenant()
    if failure:
        return failure
    return jsonify(
        [
            {"id": w.id, "name": w.name, "balance": format(w.balance, ".2f")}
            for w in Wallet.objects.filter(tenant=tenant).order_by("id")
        ]
    )


@app.post("/api/transfers/")
def create_transfer():
    tenant, failure = _tenant()
    if failure:
        return failure
    data, errors = _validate(request.get_json())
    if errors:
        return jsonify(errors), 400
    body, status, replayed = transfer_money(
        tenant, data["source"], data["destination"], data["amount"], data["idempotency_key"]
    )
    return jsonify(body), status, {"X-Idempotent-Replay": str(replayed).lower()}
