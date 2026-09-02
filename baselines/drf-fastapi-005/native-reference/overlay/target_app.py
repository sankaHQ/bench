from __future__ import annotations

import json
import os
from secrets import compare_digest
from typing import Any

# Django owns only models and the retained auth/session tables while serving.
os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from django.contrib.auth import (  # noqa: E402
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
)
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.utils import timezone  # noqa: E402
from documents.models import AccessToken, Document  # noqa: E402

ALLOW_COLLECTION = "GET, POST, HEAD, OPTIONS"
ALLOW_DETAIL = "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"
ALLOW_REVIEW = "POST, OPTIONS"
ALLOW_ROOT = "GET, HEAD, OPTIONS"

MSG_NO_CREDENTIALS = "Authentication credentials were not provided."
MSG_INVALID_TOKEN = "Invalid token."
MSG_EXPIRED_TOKEN = "Token has expired."
MSG_INACTIVE = "User inactive or deleted."
MSG_EMPTY_TOKEN_HEADER = "Invalid token header. No credentials provided."
MSG_SPACED_TOKEN_HEADER = "Invalid token header. Token string should not contain spaces."
MSG_FORBIDDEN = "You do not have permission to perform this action."

app = FastAPI(title="Native FastAPI document access service")


def _json(
    body: Any,
    *,
    status_code: int = 200,
    allow: str,
    challenge: bool = False,
) -> JSONResponse:
    headers = {"Allow": allow}
    if challenge:
        headers["WWW-Authenticate"] = "Token"
    return JSONResponse(body, status_code=status_code, headers=headers)


def _auth_error(message: str, allow: str) -> JSONResponse:
    return _json({"detail": message}, status_code=401, allow=allow, challenge=True)


def _forbidden(allow: str, message: str = MSG_FORBIDDEN) -> JSONResponse:
    return _json({"detail": message}, status_code=403, allow=allow)


def _token_authenticate(request: Request, allow: str) -> tuple[Any, Response | None, bool]:
    header = request.headers.get("authorization", "")
    parts = header.split()
    if not parts or parts[0].lower() != "token":
        return None, None, False
    if len(parts) == 1:
        return None, _auth_error(MSG_EMPTY_TOKEN_HEADER, allow), True
    if len(parts) > 2:
        return None, _auth_error(MSG_SPACED_TOKEN_HEADER, allow), True
    try:
        token = AccessToken.objects.select_related("user").get(key=parts[1])
    except AccessToken.DoesNotExist:
        return None, _auth_error(MSG_INVALID_TOKEN, allow), True
    if not token.user.is_active:
        return None, _auth_error(MSG_INACTIVE, allow), True
    if token.expires_at <= timezone.now():
        return None, _auth_error(MSG_EXPIRED_TOKEN, allow), True
    return token.user, None, True


def _session_user(request: Request) -> Any:
    session_key = request.cookies.get("sessionid")
    if not session_key:
        return None
    session = SessionStore(session_key=session_key)
    user_id = session.get(SESSION_KEY)
    backend = session.get(BACKEND_SESSION_KEY)
    session_hash = session.get(HASH_SESSION_KEY)
    if user_id is None or backend != "django.contrib.auth.backends.ModelBackend":
        return None
    user_model = get_user_model()
    try:
        user = user_model.objects.get(pk=user_id)
    except (user_model.DoesNotExist, TypeError, ValueError, OverflowError):
        return None
    if not session_hash or not compare_digest(session_hash, user.get_session_auth_hash()):
        return None
    if not user.is_active:
        return None
    return user


def _session_csrf_error(request: Request) -> str | None:
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return None
    cookie = request.cookies.get("csrftoken")
    if not cookie:
        return "CSRF Failed: CSRF cookie not set."
    header = request.headers.get("x-csrftoken")
    if not header:
        return "CSRF Failed: CSRF token missing."
    if not compare_digest(cookie, header):
        return "CSRF Failed: CSRF token from the 'X-Csrftoken' HTTP header incorrect."
    return None


def _authenticate(request: Request, allow: str) -> tuple[Any, Response | None]:
    user, error, handled = _token_authenticate(request, allow)
    if handled:
        return user, error
    user = _session_user(request)
    if user is None:
        return None, None
    csrf_error = _session_csrf_error(request)
    if csrf_error is not None:
        return None, _forbidden(allow, csrf_error)
    return user, None


def _require_user(request: Request, allow: str) -> tuple[Any, Response | None]:
    user, error = _authenticate(request, allow)
    if error is not None:
        return None, error
    if user is None:
        return None, _auth_error(MSG_NO_CREDENTIALS, allow)
    return user, None


def _get_document(request: Request) -> tuple[Document | None, str]:
    raw = request.path_params.get("pk")
    try:
        return Document.objects.get(pk=raw), ""
    except Document.DoesNotExist:
        return None, "missing"
    except (TypeError, ValueError, OverflowError):
        return None, "invalid"


def _not_found(allow: str, cause: str) -> JSONResponse:
    detail = "No Document matches the given query." if cause == "missing" else "Not found."
    return _json({"detail": detail}, status_code=404, allow=allow)


def _serialize(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "owner": document.owner_id,
        "title": document.title,
        "body": document.body,
        "reviewed": document.reviewed,
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


def _validate(payload: Any, *, partial: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        kind = type(payload).__name__
        return {}, {"non_field_errors": [f"Invalid data. Expected a dictionary, but got {kind}."]}
    validated: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    for name, max_length, required, allow_blank in (
        ("title", 100, True, False),
        ("body", 400, False, True),
    ):
        if name not in payload:
            if required and not partial:
                errors[name] = ["This field is required."]
            continue
        cleaned, field_errors = _clean_char(
            payload[name], max_length=max_length, allow_blank=allow_blank
        )
        if field_errors:
            errors[name] = field_errors
        else:
            validated[name] = cleaned
    return validated, errors


async def _read_raw_body(request: Request) -> bytes:
    return await request.body()


def _parse_json(raw: bytes, allow: str) -> tuple[Any, Response | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, _json(
            {"detail": f"JSON parse error - {exc}"},
            status_code=400,
            allow=allow,
        )


@app.get("/api/")
def api_root(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    return _json({"documents": f"{base}/api/documents/"}, allow=ALLOW_ROOT)


@app.get("/api/documents/")
def list_documents(request: Request) -> Response:
    _user, error = _authenticate(request, ALLOW_COLLECTION)
    if error is not None:
        return error
    payload = [_serialize(document) for document in Document.objects.order_by("id")]
    return _json(payload, allow=ALLOW_COLLECTION)


@app.post("/api/documents/")
def create_document(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    user, error = _require_user(request, ALLOW_COLLECTION)
    if error is not None:
        return error
    payload, parse_error = _parse_json(raw_body, ALLOW_COLLECTION)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate(payload, partial=False)
    if errors:
        return _json(errors, status_code=400, allow=ALLOW_COLLECTION)
    document = Document.objects.create(owner=user, **validated)
    return _json(_serialize(document), status_code=201, allow=ALLOW_COLLECTION)


@app.get("/api/documents/{pk}/")
def retrieve_document(request: Request) -> Response:
    user, error = _require_user(request, ALLOW_DETAIL)
    if error is not None:
        return error
    document, miss = _get_document(request)
    if document is None:
        return _not_found(ALLOW_DETAIL, miss)
    if document.owner_id != user.id:
        return _forbidden(ALLOW_DETAIL)
    return _json(_serialize(document), allow=ALLOW_DETAIL)


def _mutate_document(request: Request, raw_body: bytes, *, partial: bool) -> Response:
    user, error = _require_user(request, ALLOW_DETAIL)
    if error is not None:
        return error
    document, miss = _get_document(request)
    if document is None:
        return _not_found(ALLOW_DETAIL, miss)
    if document.owner_id != user.id:
        return _forbidden(ALLOW_DETAIL)
    payload, parse_error = _parse_json(raw_body, ALLOW_DETAIL)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate(payload, partial=partial)
    if errors:
        return _json(errors, status_code=400, allow=ALLOW_DETAIL)
    for name, value in validated.items():
        setattr(document, name, value)
    document.save()
    return _json(_serialize(document), allow=ALLOW_DETAIL)


@app.put("/api/documents/{pk}/")
def update_document(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    return _mutate_document(request, raw_body, partial=False)


@app.patch("/api/documents/{pk}/")
def partial_update_document(
    request: Request, raw_body: bytes = Depends(_read_raw_body)
) -> Response:
    return _mutate_document(request, raw_body, partial=True)


@app.delete("/api/documents/{pk}/")
def destroy_document(request: Request) -> Response:
    user, error = _require_user(request, ALLOW_DETAIL)
    if error is not None:
        return error
    if not user.is_staff:
        return _forbidden(ALLOW_DETAIL)
    document, miss = _get_document(request)
    if document is None:
        return _not_found(ALLOW_DETAIL, miss)
    document.delete()
    return Response(status_code=204, headers={"Allow": ALLOW_DETAIL})


@app.post("/api/documents/{pk}/review/")
def review_document(request: Request) -> Response:
    user, error = _require_user(request, ALLOW_REVIEW)
    if error is not None:
        return error
    if not user.is_staff:
        return _forbidden(ALLOW_REVIEW)
    document, miss = _get_document(request)
    if document is None:
        return _not_found(ALLOW_REVIEW, miss)
    document.reviewed = True
    document.save(update_fields=["reviewed"])
    return _json(_serialize(document), allow=ALLOW_REVIEW)
