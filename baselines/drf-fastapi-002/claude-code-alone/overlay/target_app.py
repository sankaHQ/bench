"""FastAPI re-implementation of the bulletin_project DRF API.

Serves the same routes/behavior as the original Django REST Framework app
(TokenAuthentication + IsAuthenticated/IsAuthorOrReadOnly on posts.PostViewSet)
without importing rest_framework or any Django request-serving machinery.
Django is used strictly as an ORM against the same BENCH_DB_PATH database,
via bulletin_project.serving_settings (rest_framework apps removed).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bulletin_project.serving_settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.db import close_old_connections, connection  # noqa: E402

from posts.models import Post  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402

app = FastAPI()

LIST_ALLOW = "GET, POST, HEAD, OPTIONS"
DETAIL_ALLOW = "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"
ROOT_ALLOW = "GET, HEAD, OPTIONS"


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str, allow: str, extra_headers: dict | None = None):
        self.status_code = status_code
        self.detail = detail
        self.allow = allow
        self.extra_headers = extra_headers or {}


async def run_django(fn, *args):
    """Django's ORM refuses synchronous DB access from a thread that has a
    running asyncio event loop, so every ORM-touching call is executed in a
    worker thread (mirroring how Django itself runs sync views under ASGI)."""

    def wrapped():
        close_old_connections()
        try:
            return fn(*args)
        finally:
            close_old_connections()

    return await run_in_threadpool(wrapped)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    headers = {"Allow": exc.allow, **exc.extra_headers}
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


def authenticate(request: Request, allow: str) -> User:
    """Replicates rest_framework.authentication.TokenAuthentication combined
    with IsAuthenticated: returns the authenticated Django user, or raises
    ApiError(401) with the same detail/WWW-Authenticate behavior as DRF."""
    www_auth_headers = {"WWW-Authenticate": "Token"}
    auth_header = request.headers.get("authorization", "")
    parts = auth_header.split()

    if not parts or parts[0].lower() != "token":
        raise ApiError(401, "Authentication credentials were not provided.", allow, www_auth_headers)

    if len(parts) == 1:
        raise ApiError(401, "Invalid token header. No credentials provided.", allow, www_auth_headers)
    if len(parts) > 2:
        raise ApiError(
            401, "Invalid token header. Token string should not contain spaces.", allow, www_auth_headers
        )

    key = parts[1]

    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id FROM authtoken_token WHERE key = %s", [key])
        row = cursor.fetchone()

    if row is None:
        raise ApiError(401, "Invalid token.", allow, www_auth_headers)

    try:
        user = User.objects.get(pk=row[0])
    except User.DoesNotExist:
        raise ApiError(401, "Invalid token.", allow, www_auth_headers)

    if not user.is_active:
        raise ApiError(401, "User inactive or deleted.", allow, www_auth_headers)

    return user


def check_object_permission(request: Request, user: User, post: Post, allow: str) -> None:
    """Replicates IsAuthorOrReadOnly.has_object_permission for an already
    authenticated request."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if post.author_id != user.id:
        raise ApiError(403, "You do not have permission to perform this action.", allow)


def get_post_or_404(post_id: int, allow: str) -> Post:
    try:
        return Post.objects.get(pk=post_id)
    except Post.DoesNotExist:
        raise ApiError(404, "No Post matches the given query.", allow)


def serialize_post(post: Post) -> dict:
    return {"id": post.id, "author": post.author_id, "title": post.title, "body": post.body}


def _validate_char_field(name: str, value, max_length: int, allow_blank: bool, errors: dict) -> str | None:
    if value is None:
        errors.setdefault(name, []).append("This field may not be null.")
        return None

    if value == "" or str(value).strip() == "":
        if not allow_blank:
            errors.setdefault(name, []).append("This field may not be blank.")
            return None
        return ""

    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        errors.setdefault(name, []).append("Not a valid string.")
        return None

    s = str(value).strip()
    if len(s) > max_length:
        errors.setdefault(name, []).append(f"Ensure this field has no more than {max_length} characters.")
        return None
    return s


def validate_post_data(data: dict, partial: bool) -> tuple[dict, dict]:
    """Replicates posts.serializers.PostSerializer field validation
    (title: required, max_length=100, not blank; body: optional,
    max_length=400, blank allowed; author/id: read-only, ignored)."""
    errors: dict[str, list[str]] = {}
    validated: dict = {}

    if "title" in data:
        value = _validate_char_field("title", data["title"], 100, allow_blank=False, errors=errors)
        if value is not None:
            validated["title"] = value
    elif not partial:
        errors.setdefault("title", []).append("This field is required.")

    if "body" in data:
        value = _validate_char_field("body", data["body"], 400, allow_blank=True, errors=errors)
        if value is not None:
            validated["body"] = value
    # body absent -> skipped entirely (DRF SkipField); model default "" applies on create.

    return validated, errors


async def read_json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@app.get("/api/")
async def api_root(request: Request):
    base = f"{request.url.scheme}://{request.url.netloc}"
    return JSONResponse({"posts": f"{base}/api/posts/"}, headers={"Allow": ROOT_ALLOW})


@app.get("/api/posts/")
async def list_posts(request: Request):
    def work():
        authenticate(request, LIST_ALLOW)
        posts = Post.objects.order_by("id")
        return [serialize_post(p) for p in posts]

    data = await run_django(work)
    return JSONResponse(data, headers={"Allow": LIST_ALLOW})


@app.post("/api/posts/")
async def create_post(request: Request):
    body = await read_json_body(request)

    def work():
        user = authenticate(request, LIST_ALLOW)
        validated, errors = validate_post_data(body, partial=False)
        if errors:
            return 400, errors
        post = Post.objects.create(
            author=user,
            title=validated["title"],
            body=validated.get("body", ""),
        )
        return 201, serialize_post(post)

    status_code, payload = await run_django(work)
    return JSONResponse(payload, status_code=status_code, headers={"Allow": LIST_ALLOW})


@app.get("/api/posts/{post_id}/")
async def retrieve_post(request: Request, post_id: int):
    def work():
        authenticate(request, DETAIL_ALLOW)
        post = get_post_or_404(post_id, DETAIL_ALLOW)
        return serialize_post(post)

    data = await run_django(work)
    return JSONResponse(data, headers={"Allow": DETAIL_ALLOW})


async def _update_post(request: Request, post_id: int, partial: bool):
    body = await read_json_body(request)

    def work():
        user = authenticate(request, DETAIL_ALLOW)
        post = get_post_or_404(post_id, DETAIL_ALLOW)
        check_object_permission(request, user, post, DETAIL_ALLOW)
        validated, errors = validate_post_data(body, partial=partial)
        if errors:
            return 400, errors
        for attr, value in validated.items():
            setattr(post, attr, value)
        post.save()
        return 200, serialize_post(post)

    status_code, payload = await run_django(work)
    return JSONResponse(payload, status_code=status_code, headers={"Allow": DETAIL_ALLOW})


@app.put("/api/posts/{post_id}/")
async def update_post(request: Request, post_id: int):
    return await _update_post(request, post_id, partial=False)


@app.patch("/api/posts/{post_id}/")
async def partial_update_post(request: Request, post_id: int):
    return await _update_post(request, post_id, partial=True)


@app.delete("/api/posts/{post_id}/")
async def delete_post(request: Request, post_id: int):
    def work():
        user = authenticate(request, DETAIL_ALLOW)
        post = get_post_or_404(post_id, DETAIL_ALLOW)
        check_object_permission(request, user, post, DETAIL_ALLOW)
        post.delete()

    await run_django(work)
    return Response(status_code=204, headers={"Allow": DETAIL_ALLOW})
