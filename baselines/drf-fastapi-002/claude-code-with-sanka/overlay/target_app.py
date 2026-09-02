"""FastAPI replacement for the DRF bulletin-board app.

Django is used strictly as an ORM (via bulletin_project.serving_settings,
which strips every rest_framework app out of INSTALLED_APPS). No Django
request-serving machinery (django.core.asgi/wsgi/handlers, django.test) and
no rest_framework import happen anywhere in this process.
"""

from __future__ import annotations

import os
import re

os.environ["DJANGO_SETTINGS_MODULE"] = "bulletin_project.serving_settings"

import django
from django.conf import settings as django_settings

if not django_settings.configured:
    django.setup()

from django.db import close_old_connections

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from posts.serving_models import AuthToken

app = FastAPI()


# ---------------------------------------------------------------------------
# Errors that mirror DRF's exception -> response mapping.
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail


class ValidationApiError(Exception):
    def __init__(self, errors: dict) -> None:
        self.errors = errors


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ValidationApiError)
async def validation_error_handler(request: Request, exc: ValidationApiError) -> JSONResponse:
    return JSONResponse(status_code=400, content=exc.errors)


# ---------------------------------------------------------------------------
# DRF-equivalent "Allow" / "WWW-Authenticate" headers, applied uniformly to
# every response for a route regardless of success/error, matching how DRF's
# APIView.dispatch sets self.headers before authentication/permissions run.
# ---------------------------------------------------------------------------

_ROOT_RE = re.compile(r"^/api/?$")
_LIST_RE = re.compile(r"^/api/posts/?$")
_DETAIL_RE = re.compile(r"^/api/posts/[^/]+/?$")


@app.middleware("http")
async def add_drf_style_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if _DETAIL_RE.match(path):
        response.headers["Allow"] = "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"
    elif _LIST_RE.match(path):
        response.headers["Allow"] = "GET, POST, HEAD, OPTIONS"
    elif _ROOT_RE.match(path):
        response.headers["Allow"] = "GET, HEAD, OPTIONS"
    if response.status_code == 401:
        response.headers["WWW-Authenticate"] = "Token"
    return response


# ---------------------------------------------------------------------------
# Auth + permissions (mirrors rest_framework.authentication.TokenAuthentication,
# rest_framework.permissions.IsAuthenticated, posts.permissions.IsAuthorOrReadOnly).
# ---------------------------------------------------------------------------


def authenticate_request(auth_header: str | None):
    if not auth_header:
        return None
    parts = auth_header.split()
    if not parts or parts[0].lower() != "token":
        return None
    if len(parts) == 1:
        raise ApiError(401, "Invalid token header. No credentials provided.")
    if len(parts) > 2:
        raise ApiError(401, "Invalid token header. Token string should not contain spaces.")
    key = parts[1]
    try:
        token = AuthToken.objects.select_related("user").get(key=key)
    except AuthToken.DoesNotExist:
        raise ApiError(401, "Invalid token.")
    if not token.user.is_active:
        raise ApiError(401, "User inactive or deleted.")
    return token.user


def require_authenticated(user) -> None:
    if user is None:
        raise ApiError(401, "Authentication credentials were not provided.")


def check_author_permission(user, post) -> None:
    if post.author_id != user.id:
        raise ApiError(403, "You do not have permission to perform this action.")


# ---------------------------------------------------------------------------
# Serialization + validation (mirrors posts.serializers.PostSerializer).
# ---------------------------------------------------------------------------


def serialize_post(post) -> dict:
    return {"id": post.id, "author": post.author_id, "title": post.title, "body": post.body}


def validate_post_data(data: dict, partial: bool) -> tuple[dict, dict]:
    errors: dict[str, list[str]] = {}
    cleaned: dict = {}

    if "title" in data:
        title = data["title"]
        if title is None:
            errors.setdefault("title", []).append("This field may not be null.")
        elif not isinstance(title, str):
            errors.setdefault("title", []).append("Not a valid string.")
        elif title == "":
            errors.setdefault("title", []).append("This field may not be blank.")
        elif len(title) > 100:
            errors.setdefault("title", []).append("Ensure this field has no more than 100 characters.")
        else:
            cleaned["title"] = title
    elif not partial:
        errors.setdefault("title", []).append("This field is required.")

    if "body" in data:
        body = data["body"]
        if body is None:
            errors.setdefault("body", []).append("This field may not be null.")
        elif not isinstance(body, str):
            errors.setdefault("body", []).append("Not a valid string.")
        elif len(body) > 400:
            errors.setdefault("body", []).append("Ensure this field has no more than 400 characters.")
        else:
            cleaned["body"] = body

    return cleaned, errors


def get_post_or_404(pk: str):
    from posts.models import Post

    try:
        pk_int = int(pk)
    except (TypeError, ValueError):
        raise ApiError(404, "Not found.")
    try:
        return Post.objects.get(pk=pk_int)
    except Post.DoesNotExist:
        raise ApiError(404, "Not found.")


def run_sync(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    finally:
        close_old_connections()


async def _parse_json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# ---------------------------------------------------------------------------
# Routes (mirrors bulletin_project.urls / posts.views.PostViewSet).
# ---------------------------------------------------------------------------


@app.get("/api/")
async def api_root(request: Request) -> JSONResponse:
    base = str(request.base_url).rstrip("/")
    return JSONResponse(content={"posts": f"{base}/api/posts/"})


@app.get("/api/posts/")
async def list_posts(request: Request) -> JSONResponse:
    def work():
        from posts.models import Post

        user = authenticate_request(request.headers.get("authorization"))
        require_authenticated(user)
        posts = Post.objects.all().order_by("id")
        return [serialize_post(p) for p in posts]

    data = await run_in_threadpool(run_sync, work)
    return JSONResponse(content=data)


@app.post("/api/posts/")
async def create_post(request: Request) -> JSONResponse:
    body = await _parse_json_body(request)

    def work():
        from posts.models import Post

        user = authenticate_request(request.headers.get("authorization"))
        require_authenticated(user)
        cleaned, errors = validate_post_data(body, partial=False)
        if errors:
            raise ValidationApiError(errors)
        post = Post.objects.create(author=user, title=cleaned["title"], body=cleaned.get("body", ""))
        return serialize_post(post)

    data = await run_in_threadpool(run_sync, work)
    return JSONResponse(content=data, status_code=201)


@app.get("/api/posts/{pk}/")
async def retrieve_post(pk: str, request: Request) -> JSONResponse:
    def work():
        user = authenticate_request(request.headers.get("authorization"))
        require_authenticated(user)
        post = get_post_or_404(pk)
        return serialize_post(post)

    data = await run_in_threadpool(run_sync, work)
    return JSONResponse(content=data)


async def _update_post(pk: str, request: Request, partial: bool) -> JSONResponse:
    body = await _parse_json_body(request)

    def work():
        user = authenticate_request(request.headers.get("authorization"))
        require_authenticated(user)
        post = get_post_or_404(pk)
        check_author_permission(user, post)
        cleaned, errors = validate_post_data(body, partial=partial)
        if errors:
            raise ValidationApiError(errors)
        if "title" in cleaned:
            post.title = cleaned["title"]
        if "body" in cleaned:
            post.body = cleaned["body"]
        post.save()
        return serialize_post(post)

    data = await run_in_threadpool(run_sync, work)
    return JSONResponse(content=data)


@app.put("/api/posts/{pk}/")
async def update_post(pk: str, request: Request) -> JSONResponse:
    return await _update_post(pk, request, partial=False)


@app.patch("/api/posts/{pk}/")
async def partial_update_post(pk: str, request: Request) -> JSONResponse:
    return await _update_post(pk, request, partial=True)


@app.delete("/api/posts/{pk}/")
async def destroy_post(pk: str, request: Request) -> Response:
    def work():
        user = authenticate_request(request.headers.get("authorization"))
        require_authenticated(user)
        post = get_post_or_404(pk)
        check_author_permission(user, post)
        post.delete()

    await run_in_threadpool(run_sync, work)
    return Response(status_code=204)
