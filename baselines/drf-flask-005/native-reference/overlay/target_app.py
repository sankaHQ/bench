# ruff: noqa: E402
import os

os.environ["DJANGO_SETTINGS_MODULE"] = "serving_settings"
import django

django.setup()
from flask import Flask, Response, jsonify, request

app = Flask(__name__)


class SourceHeadersResponse(Response):
    def get_wsgi_headers(self, environ):
        result = super().get_wsgi_headers(environ)
        # DRF retains Allow on 304; Werkzeug normally strips this header.
        if self.status_code == 304 and "Allow" in self.headers:
            result["Allow"] = self.headers["Allow"]
        return result


app.response_class = SourceHeadersResponse


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


from documents.logic import headers, matches, mutate, representation
from documents.models import Document


@app.after_request
def add_allow(response):
    response.headers["Allow"] = "GET, PATCH, DELETE, HEAD, OPTIONS"
    return response


@app.route(
    "/api/documents/<int:identifier>/",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def document(identifier):
    user, error = owner()
    if error is not None:
        return error
    if request.method in {"GET", "HEAD"}:
        row = Document.objects.filter(id=identifier, owner=user, deleted=False).first()
        if row is None:
            return respond({"detail": "Document not found."}, 404)
        if matches(request.headers.get("If-None-Match", ""), row, weak=True):
            return respond(None, 304, headers(row))
        return respond(representation(row), 200, headers(row))
    if request.method == "OPTIONS":
        return respond(
            {
                "name": "Document",
                "description": "",
                "renders": ["application/json"],
                "parses": ["application/json"],
            }
        )
    if request.method == "PATCH":
        data = request.get_json(silent=True)
        values, errors = validate(
            {} if data is None else data,
            [
                ("title", "str", False, None, 64, True, False),
                ("body", "str", False, None, 1024, False, True),
            ],
        )
        if not errors and not values:
            errors = {"non_field_errors": ["Provide title or body."]}
        if errors:
            return respond(errors, 400)
        return respond(*mutate(user, identifier, request.headers.get("If-Match", ""), values))
    if request.method == "DELETE":
        return respond(
            *mutate(user, identifier, request.headers.get("If-Match", ""), {}, delete=True)
        )
    return respond({"detail": f'Method "{request.method}" not allowed.'}, 405)
