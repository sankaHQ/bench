# ruff: noqa: E402
import os

os.environ["DJANGO_SETTINGS_MODULE"] = "serving_settings"
import django

django.setup()
from flask import Flask, jsonify, request

app = Flask(__name__)


def respond(data, status=200, headers=None):
    result = app.response_class() if data is None else jsonify(data)
    result.status_code = status
    if headers:
        result.headers.update(headers)
    return result


def owner():
    header = request.headers.get("Authorization", "")
    value = {"ApiKey team-a": "alpha", "ApiKey team-b": "beta"}.get(header)
    if value:
        return value, None
    detail = "Invalid API key." if header else "Authentication credentials were not provided."
    return None, respond({"detail": detail}, 401, {"WWW-Authenticate": "ApiKey"})


def validate(data, fields):
    if not isinstance(data, dict):
        return {}, {
            "non_field_errors": [
                "Invalid data. Expected a dictionary, but got " + type(data).__name__ + "."
            ]
        }
    values, errors = {}, {}
    for name, kind, required, minimum, maximum, trim, blank in fields:
        if name not in data:
            if required:
                errors[name] = ["This field is required."]
            continue
        value = data[name]
        if value is None:
            errors[name] = ["This field may not be null."]
            continue
        if kind == "int":
            try:
                import re

                value = int(re.sub(r"\.0*\s*$", "", str(value)))
            except (ValueError, TypeError):
                errors[name] = ["A valid integer is required."]
                continue
            if minimum is not None and value < minimum:
                errors[name] = [f"Ensure this value is greater than or equal to {minimum}."]
            if maximum is not None and value > maximum:
                errors[name] = [f"Ensure this value is less than or equal to {maximum}."]
        else:
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                errors[name] = ["Not a valid string."]
                continue
            value = str(value)
            if trim:
                value = value.strip()
            if not value and not blank:
                errors[name] = ["This field may not be blank."]
            elif maximum is not None and len(value) > maximum:
                errors[name] = [f"Ensure this field has no more than {maximum} characters."]
        if name not in errors:
            values[name] = value
    return values, errors


from reservations.logic import book, cancel, representation
from reservations.models import Reservation


@app.after_request
def add_allow(response):
    response.headers["Allow"] = (
        "POST, OPTIONS" if request.path.endswith("/cancel/") else "GET, POST, HEAD, OPTIONS"
    )
    return response


@app.route("/api/bookings/", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def bookings():
    user, error = owner()
    if error is not None:
        return error
    if request.method in {"GET", "HEAD"}:
        return respond(
            [
                representation(row)
                for row in Reservation.objects.filter(resource__owner=user).order_by("start", "id")
            ]
        )
    if request.method == "OPTIONS":
        return respond(
            {
                "name": "Booking",
                "description": "",
                "renders": ["application/json"],
                "parses": ["application/json"],
            }
        )
    if request.method != "POST":
        return respond({"detail": f'Method "{request.method}" not allowed.'}, 405)
    data = request.get_json(silent=True)
    values, errors = validate(
        {} if data is None else data,
        [
            ("resource", "int", True, 1, None, False, False),
            ("start", "str", True, None, None, True, False),
            ("end", "str", True, None, None, True, False),
            ("timezone", "str", True, None, None, True, False),
            ("fold", "int", False, 0, 1, False, False),
            ("seats", "int", True, 1, 20, False, False),
        ],
    )
    return respond(errors, 400) if errors else respond(*book(user, values))


@app.route(
    "/api/bookings/<int:identifier>/cancel/",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def cancellation(identifier):
    user, error = owner()
    if error is not None:
        return error
    if request.method == "OPTIONS":
        return respond(
            {
                "name": "Cancel",
                "description": "",
                "renders": ["application/json"],
                "parses": ["application/json"],
            }
        )
    if request.method != "POST":
        return respond({"detail": f'Method "{request.method}" not allowed.'}, 405)
    return respond(*cancel(user, identifier))
