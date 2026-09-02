from __future__ import annotations

import os
from typing import Any

os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from catalog.models import Entry  # noqa: E402

app = FastAPI(title="Native FastAPI mixed-style reference")
REQUEST_BODY = Body(...)
VALID_STATES = {"draft", "published"}


def _serialize(entry: Entry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "code": entry.code,
        "title": entry.title,
        "body": entry.body,
        "state": entry.state,
    }


def _not_found() -> JSONResponse:
    return JSONResponse(
        {"detail": "No Entry matches the given query."},
        status_code=404,
    )


def _get_entry(code: str) -> Entry | None:
    return Entry.objects.filter(code=code).first()


def _text(value: Any) -> str:
    return str(value).strip()


def _validation_errors(
    payload: dict[str, Any],
    *,
    instance: Entry | None,
    partial: bool,
) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for field in ("code", "title"):
        if not partial and field not in payload:
            errors[field] = ["This field is required."]
        elif field in payload and not _text(payload[field]):
            errors[field] = ["This field may not be blank."]

    if "code" in payload and "code" not in errors:
        code = _text(payload["code"])
        if len(code) > 80:
            errors["code"] = ["Ensure this field has no more than 80 characters."]
        else:
            duplicate = Entry.objects.filter(code=code)
            if instance is not None:
                duplicate = duplicate.exclude(pk=instance.pk)
            if duplicate.exists():
                errors["code"] = ["entry with this code already exists."]

    if "title" in payload and "title" not in errors and len(_text(payload["title"])) > 120:
        errors["title"] = ["Ensure this field has no more than 120 characters."]

    if "state" in payload and payload["state"] not in VALID_STATES:
        errors["state"] = [f'"{payload["state"]}" is not a valid choice.']
    return errors


def _write(
    payload: dict[str, Any],
    *,
    instance: Entry | None = None,
    partial: bool = False,
) -> Response:
    errors = _validation_errors(payload, instance=instance, partial=partial)
    if errors:
        return JSONResponse(errors, status_code=400)

    entry = instance or Entry()
    if "code" in payload:
        entry.code = _text(payload["code"])
    if "title" in payload:
        entry.title = _text(payload["title"])
    if "body" in payload:
        entry.body = _text(payload["body"])
    if "state" in payload:
        entry.state = str(payload["state"])
    entry.save()
    return JSONResponse(_serialize(entry), status_code=200 if instance else 201)


def _list() -> JSONResponse:
    return JSONResponse([_serialize(entry) for entry in Entry.objects.order_by("id")])


def _retrieve(code: str) -> Response:
    entry = _get_entry(code)
    return JSONResponse(_serialize(entry)) if entry is not None else _not_found()


def _update(code: str, payload: dict[str, Any], *, partial: bool) -> Response:
    entry = _get_entry(code)
    if entry is None:
        return _not_found()
    return _write(payload, instance=entry, partial=partial)


def _delete(code: str) -> Response:
    entry = _get_entry(code)
    if entry is None:
        return _not_found()
    entry.delete()
    return Response(status_code=204)


def _method_not_allowed(method: str, allow: str) -> JSONResponse:
    return JSONResponse(
        {"detail": f'Method "{method}" not allowed.'},
        status_code=405,
        headers={"Allow": allow},
    )


def _redirect(request: Request, target: str) -> Response:
    location = f"{str(request.base_url).rstrip('/')}{target}"
    return Response(status_code=307, headers={"Location": location})


@app.get("/api/function/entries")
@app.get("/api/function/entries/")
def function_list_entries() -> Response:
    return _list()


@app.post("/api/function/entries")
@app.post("/api/function/entries/")
def function_create_entry(payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _write(payload)


@app.put("/api/function/entries")
@app.put("/api/function/entries/")
def function_collection_put() -> Response:
    return _method_not_allowed("PUT", "POST, OPTIONS, GET")


@app.get("/api/function/entries/{code}")
@app.get("/api/function/entries/{code}/")
def function_retrieve_entry(code: str) -> Response:
    return _retrieve(code)


@app.put("/api/function/entries/{code}")
@app.put("/api/function/entries/{code}/")
def function_update_entry(code: str, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _update(code, payload, partial=False)


@app.patch("/api/function/entries/{code}")
@app.patch("/api/function/entries/{code}/")
def function_patch_entry(code: str, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _update(code, payload, partial=True)


@app.delete("/api/function/entries/{code}")
@app.delete("/api/function/entries/{code}/")
def function_delete_entry(code: str) -> Response:
    return _delete(code)


@app.post("/api/function/entries/{code}")
@app.post("/api/function/entries/{code}/")
def function_detail_post(code: str) -> Response:
    return _method_not_allowed("POST", "PUT, PATCH, DELETE, OPTIONS, GET")


@app.get("/api/class/entries")
def class_list_entries() -> Response:
    return _list()


@app.post("/api/class/entries")
def class_create_entry(payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _write(payload)


@app.put("/api/class/entries")
def class_collection_put() -> Response:
    return _method_not_allowed("PUT", "GET, POST, HEAD, OPTIONS")


@app.get("/api/class/entries/")
def class_collection_redirect(request: Request) -> Response:
    return _redirect(request, "/api/class/entries")


@app.get("/api/class/entries/{code}")
def class_retrieve_entry(code: str) -> Response:
    return _retrieve(code)


@app.put("/api/class/entries/{code}")
def class_update_entry(code: str, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _update(code, payload, partial=False)


@app.patch("/api/class/entries/{code}")
def class_patch_entry(code: str, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _update(code, payload, partial=True)


@app.delete("/api/class/entries/{code}")
def class_delete_entry(code: str) -> Response:
    return _delete(code)


@app.post("/api/class/entries/{code}")
def class_detail_post(code: str) -> Response:
    return _method_not_allowed("POST", "GET, PUT, PATCH, DELETE, HEAD, OPTIONS")


@app.get("/api/class/entries/{code}/")
def class_detail_redirect(code: str, request: Request) -> Response:
    return _redirect(request, f"/api/class/entries/{code}")


@app.get("/api/viewset/entries/")
def viewset_list_entries() -> Response:
    return _list()


@app.post("/api/viewset/entries/")
def viewset_create_entry(payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _write(payload)


@app.put("/api/viewset/entries/")
def viewset_collection_put() -> Response:
    return _method_not_allowed("PUT", "GET, POST, HEAD, OPTIONS")


@app.get("/api/viewset/entries")
def viewset_collection_redirect(request: Request) -> Response:
    return _redirect(request, "/api/viewset/entries/")


@app.get("/api/viewset/entries/{code}/")
def viewset_retrieve_entry(code: str) -> Response:
    return _retrieve(code)


@app.put("/api/viewset/entries/{code}/")
def viewset_update_entry(code: str, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _update(code, payload, partial=False)


@app.patch("/api/viewset/entries/{code}/")
def viewset_patch_entry(code: str, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    return _update(code, payload, partial=True)


@app.delete("/api/viewset/entries/{code}/")
def viewset_delete_entry(code: str) -> Response:
    return _delete(code)


@app.post("/api/viewset/entries/{code}/")
def viewset_detail_post(code: str) -> Response:
    return _method_not_allowed("POST", "GET, PUT, PATCH, DELETE, HEAD, OPTIONS")


@app.get("/api/viewset/entries/{code}")
def viewset_detail_redirect(code: str, request: Request) -> Response:
    return _redirect(request, f"/api/viewset/entries/{code}/")


@app.get("/api/dynamic/entries/{code}/")
def dynamic_retrieve_entry(code: str) -> Response:
    return _retrieve(code)


@app.get("/api/viewset/")
def viewset_api_root() -> JSONResponse:
    return JSONResponse({"entries": "http://testserver/api/viewset/entries/"})
