from __future__ import annotations

import json
import os
from typing import Any

# The serving process owns its configuration: Django keeps only the ORM half
# of the source application; no rest_framework app is loaded.
os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from django.db import models as dj_models  # noqa: E402
from posts.models import Post  # noqa: E402


class ServingToken(dj_models.Model):
    """Unmanaged mirror of the authtoken table; DRF itself is not imported."""

    key = dj_models.CharField(primary_key=True, max_length=40)
    user = dj_models.ForeignKey("auth.User", on_delete=dj_models.CASCADE, related_name="+")

    class Meta:
        app_label = "posts"
        db_table = "authtoken_token"
        managed = False


ALLOW_COLLECTION = "GET, POST, HEAD, OPTIONS"
ALLOW_DETAIL = "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"
ALLOW_ROOT = "GET, HEAD, OPTIONS"

MSG_NO_CREDENTIALS = "Authentication credentials were not provided."
MSG_INVALID_TOKEN = "Invalid token."
MSG_EMPTY_TOKEN_HEADER = "Invalid token header. No credentials provided."
MSG_SPACED_TOKEN_HEADER = "Invalid token header. Token string should not contain spaces."
MSG_FORBIDDEN = "You do not have permission to perform this action."

app = FastAPI(title="Native FastAPI bulletin service")


def _auth_error(message: str, allow: str) -> JSONResponse:
    return JSONResponse(
        {"detail": message},
        status_code=401,
        headers={"Allow": allow, "WWW-Authenticate": "Token"},
    )


def _authenticate(request: Request, allow: str) -> tuple[int | None, JSONResponse | None]:
    header = request.headers.get("authorization", "")
    parts = header.split()
    if not parts or parts[0].lower() != "token":
        return None, None
    if len(parts) == 1:
        return None, _auth_error(MSG_EMPTY_TOKEN_HEADER, allow)
    if len(parts) > 2:
        return None, _auth_error(MSG_SPACED_TOKEN_HEADER, allow)
    user_id = ServingToken.objects.filter(key=parts[1]).values_list("user_id", flat=True).first()
    if user_id is None:
        return None, _auth_error(MSG_INVALID_TOKEN, allow)
    return int(user_id), None


def _require_user(request: Request, allow: str) -> tuple[int | None, JSONResponse | None]:
    user_id, error = _authenticate(request, allow)
    if error is not None:
        return None, error
    if user_id is None:
        return None, _auth_error(MSG_NO_CREDENTIALS, allow)
    return user_id, None


def _forbidden(allow: str) -> JSONResponse:
    return JSONResponse({"detail": MSG_FORBIDDEN}, status_code=403, headers={"Allow": allow})


def _not_found(allow: str, cause: str) -> JSONResponse:
    detail = "No Post matches the given query." if cause == "missing" else "Not found."
    return JSONResponse({"detail": detail}, status_code=404, headers={"Allow": allow})


def _get_post(request: Request) -> tuple[Post | None, str]:
    raw = request.path_params.get("pk")
    try:
        return Post.objects.get(pk=raw), ""
    except Post.DoesNotExist:
        return None, "missing"
    except (TypeError, ValueError, OverflowError):
        return None, "invalid"


def _serialize(post: Post) -> dict[str, Any]:
    return {"id": post.id, "author": post.author_id, "title": post.title, "body": post.body}


def _validate(payload: Any, *, partial: bool) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if not isinstance(payload, dict):
        message = f"Invalid data. Expected a dictionary, but got {type(payload).__name__}."
        return {}, {"non_field_errors": [message]}
    errors: dict[str, list[str]] = {}
    validated: dict[str, Any] = {}
    for name, max_length, required, allow_blank in (
        ("title", 100, True, False),
        ("body", 400, False, True),
    ):
        if name not in payload:
            if not partial and required:
                errors[name] = ["This field is required."]
            continue
        value = payload[name]
        if value is None:
            errors[name] = ["This field may not be null."]
            continue
        if value == "" or (isinstance(value, str) and not value.strip()):
            if allow_blank:
                validated[name] = ""
            else:
                errors[name] = ["This field may not be blank."]
            continue
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            errors[name] = ["Not a valid string."]
            continue
        cleaned = str(value).strip()
        if len(cleaned) > max_length:
            errors[name] = [f"Ensure this field has no more than {max_length} characters."]
            continue
        validated[name] = cleaned
    return validated, errors


async def _read_raw_body(request: Request) -> bytes:
    return await request.body()


def _parse_json(raw: bytes, allow: str) -> tuple[Any, JSONResponse | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, JSONResponse(
            {"detail": f"JSON parse error - {exc}"}, status_code=400, headers={"Allow": allow}
        )


@app.get("/api/")
def api_root(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    return JSONResponse({"posts": f"{base}/api/posts/"}, headers={"Allow": ALLOW_ROOT})


@app.get("/api/posts/")
def list_posts(request: Request) -> Response:
    _, error = _require_user(request, ALLOW_COLLECTION)
    if error is not None:
        return error
    payload = [_serialize(post) for post in Post.objects.order_by("id")]
    return JSONResponse(payload, headers={"Allow": ALLOW_COLLECTION})


@app.post("/api/posts/")
def create_post(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    user_id, error = _require_user(request, ALLOW_COLLECTION)
    if error is not None:
        return error
    payload, parse_error = _parse_json(raw_body, ALLOW_COLLECTION)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate(payload, partial=False)
    if errors:
        return JSONResponse(errors, status_code=400, headers={"Allow": ALLOW_COLLECTION})
    post = Post.objects.create(author_id=user_id, **validated)
    return JSONResponse(_serialize(post), status_code=201, headers={"Allow": ALLOW_COLLECTION})


@app.get("/api/posts/{pk}/")
def retrieve_post(request: Request) -> Response:
    _, error = _require_user(request, ALLOW_DETAIL)
    if error is not None:
        return error
    post, miss = _get_post(request)
    if post is None:
        return _not_found(ALLOW_DETAIL, miss)
    return JSONResponse(_serialize(post), headers={"Allow": ALLOW_DETAIL})


def _mutate(request: Request, raw_body: bytes, *, partial: bool) -> Response:
    user_id, error = _require_user(request, ALLOW_DETAIL)
    if error is not None:
        return error
    post, miss = _get_post(request)
    if post is None:
        return _not_found(ALLOW_DETAIL, miss)
    if post.author_id != user_id:
        return _forbidden(ALLOW_DETAIL)
    payload, parse_error = _parse_json(raw_body, ALLOW_DETAIL)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate(payload, partial=partial)
    if errors:
        return JSONResponse(errors, status_code=400, headers={"Allow": ALLOW_DETAIL})
    for name, value in validated.items():
        setattr(post, name, value)
    post.save()
    return JSONResponse(_serialize(post), headers={"Allow": ALLOW_DETAIL})


@app.put("/api/posts/{pk}/")
def update_post(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    return _mutate(request, raw_body, partial=False)


@app.patch("/api/posts/{pk}/")
def partial_update_post(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    return _mutate(request, raw_body, partial=True)


@app.delete("/api/posts/{pk}/")
def destroy_post(request: Request) -> Response:
    user_id, error = _require_user(request, ALLOW_DETAIL)
    if error is not None:
        return error
    post, miss = _get_post(request)
    if post is None:
        return _not_found(ALLOW_DETAIL, miss)
    if post.author_id != user_id:
        return _forbidden(ALLOW_DETAIL)
    post.delete()
    return Response(status_code=204, headers={"Allow": ALLOW_DETAIL})
