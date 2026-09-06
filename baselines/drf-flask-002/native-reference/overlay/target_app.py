from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from flask import Flask, Request, request
from flask import Response as FlaskResponse

os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
import django
from django.core.files.base import ContentFile

django.setup()


def JSONResponse(content, status_code=200, headers=None, media_type="application/json"):
    return FlaskResponse(
        json.dumps(content, ensure_ascii=False, separators=(",", ":")),
        status=status_code,
        headers=headers,
        content_type=media_type,
    )


def Response(content=b"", status_code=200, headers=None, media_type=None):
    return FlaskResponse(content, status=status_code, headers=headers, content_type=media_type)


from artifacts.models import Artifact  # noqa: E402

app = Flask(__name__)
ALLOWED_EXTENSIONS = {".csv", ".json", ".txt"}
MAX_UPLOAD_BYTES = 32
API_MEDIA_TYPE = "application/vnd.sanka.file+json"


def _serialize(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "key": artifact.key,
        "label": artifact.label,
        "original_name": artifact.original_name,
        "content_type": artifact.content_type,
        "byte_size": artifact.byte_size,
        "sha256": artifact.sha256,
        "download_path": f"/api/files/{artifact.pk}/download/",
    }


def _json(payload: Any, *, media_type: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code, media_type=media_type)


def _not_found(*, media_type: str) -> JSONResponse:
    return _json(
        {"detail": "No Artifact matches the given query."}, status_code=404, media_type=media_type
    )


def _get_artifact(identifier: int) -> Artifact | None:
    return Artifact.objects.filter(pk=identifier).first()


def _list(*, media_type: str) -> JSONResponse:
    return _json(
        [_serialize(artifact) for artifact in Artifact.objects.order_by("id")],
        media_type=media_type,
    )


def _detail(identifier: int, *, media_type: str) -> Response:
    artifact = _get_artifact(identifier)
    if artifact is None:
        return _not_found(media_type=media_type)
    return _json(_serialize(artifact), media_type=media_type)


def _parse_multipart(content_type: str, content: bytes) -> tuple[dict[str, str], dict[str, Any]]:
    fields: dict[str, str] = {}
    upload: dict[str, Any] = {}
    boundary_match = re.search('boundary=(?:\\"([^\\"]+)\\"|([^;]+))', content_type)
    if boundary_match is None:
        return (fields, upload)
    boundary = (boundary_match.group(1) or boundary_match.group(2)).strip().encode("latin-1")
    for raw_part in content.split(b"--" + boundary)[1:]:
        if raw_part.startswith(b"--"):
            break
        part = raw_part.removeprefix(b"\r\n")
        if b"\r\n\r\n" not in part:
            continue
        (raw_headers, value) = part.split(b"\r\n\r\n", 1)
        value = value.removesuffix(b"\r\n")
        headers = raw_headers.decode("latin-1")
        name_match = re.search('name="([^"]+)"', headers)
        if name_match is None:
            continue
        name = name_match.group(1)
        filename_match = re.search('filename="([^"]*)"', headers)
        if filename_match is None:
            fields[name] = value.decode("utf-8")
            continue
        if name == "file":
            type_match = re.search("(?im)^Content-Type:\\s*([^\\r\\n]+)", headers)
            upload = {
                "filename": Path(filename_match.group(1)).name,
                "content_type": type_match.group(1).strip()
                if type_match is not None
                else "application/octet-stream",
                "content": value,
            }
    return (fields, upload)


def _validation_errors(fields: dict[str, str], upload: dict[str, Any]) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    key = fields.get("key")
    label = fields.get("label")
    if key is None:
        errors["key"] = ["This field is required."]
    elif not key.strip():
        errors["key"] = ["This field may not be blank."]
    elif len(key.strip()) > 80:
        errors["key"] = ["Ensure this field has no more than 80 characters."]
    elif Artifact.objects.filter(key=key.strip()).exists():
        errors["key"] = ["artifact with this key already exists."]
    if label is None:
        errors["label"] = ["This field is required."]
    elif not label.strip():
        errors["label"] = ["This field may not be blank."]
    elif len(label.strip()) > 120:
        errors["label"] = ["Ensure this field has no more than 120 characters."]
    if not upload:
        errors["file"] = ["No file was submitted."]
    else:
        suffix = Path(str(upload["filename"])).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            errors["file"] = ["Only files with .csv, .json, or .txt extensions are allowed."]
        elif len(upload["content"]) > MAX_UPLOAD_BYTES:
            errors["file"] = [f"File must be {MAX_UPLOAD_BYTES} bytes or smaller."]
    return errors


def _create(request: Request, *, media_type: str) -> Response:
    content = request.get_data()
    (fields, upload) = _parse_multipart(request.headers.get("content-type", ""), content)
    errors = _validation_errors(fields, upload)
    if errors:
        return _json(errors, status_code=400, media_type=media_type)
    file_content = bytes(upload["content"])
    artifact = Artifact(
        key=fields["key"].strip(),
        label=fields["label"].strip(),
        original_name=str(upload["filename"]),
        content_type=str(upload["content_type"]),
        byte_size=len(file_content),
        sha256=hashlib.sha256(file_content).hexdigest(),
    )
    artifact.file.save(artifact.original_name, ContentFile(file_content), save=False)
    artifact.save()
    return _json(_serialize(artifact), status_code=201, media_type=media_type)


def _download(identifier: int, *, media_type: str) -> Response:
    artifact = _get_artifact(identifier)
    if artifact is None:
        return _not_found(media_type=media_type)
    content = artifact.file.read()
    return Response(
        content,
        headers={
            "Content-Type": artifact.content_type,
            "Content-Length": str(len(content)),
            "Content-Disposition": f'attachment; filename="{artifact.original_name}"',
        },
    )


@app.route("/api/files/", methods=["GET"], provide_automatic_options=False)
def list_canonical() -> Response:
    return _list(media_type="application/json")


@app.route("/api/files/", methods=["POST"], provide_automatic_options=False)
def create_canonical() -> Response:
    return _create(request, media_type="application/json")


@app.route("/api/files.json", methods=["GET"], provide_automatic_options=False)
def list_json() -> Response:
    return _list(media_type="application/json")


@app.route("/api/files.json", methods=["POST"], provide_automatic_options=False)
def create_json() -> Response:
    return _create(request, media_type="application/json")


@app.route("/api/files.api", methods=["GET"], provide_automatic_options=False)
def list_api() -> Response:
    return _list(media_type=API_MEDIA_TYPE)


@app.route("/api/files.api", methods=["POST"], provide_automatic_options=False)
def create_api() -> Response:
    return _create(request, media_type=API_MEDIA_TYPE)


@app.route("/api/files/<int:identifier>/", methods=["GET"], provide_automatic_options=False)
def detail_canonical(identifier: int) -> Response:
    return _detail(identifier, media_type="application/json")


@app.route("/api/files/<int:identifier>.json", methods=["GET"], provide_automatic_options=False)
def detail_json(identifier: int) -> Response:
    return _detail(identifier, media_type="application/json")


@app.route("/api/files/<int:identifier>.api", methods=["GET"], provide_automatic_options=False)
def detail_api(identifier: int) -> Response:
    return _detail(identifier, media_type=API_MEDIA_TYPE)


@app.route(
    "/api/files/<int:identifier>/download/", methods=["GET"], provide_automatic_options=False
)
def download_canonical(identifier: int) -> Response:
    return _download(identifier, media_type="application/json")


@app.route(
    "/api/files/<int:identifier>/download.json", methods=["GET"], provide_automatic_options=False
)
def download_json(identifier: int) -> Response:
    return _download(identifier, media_type="application/json")


@app.route(
    "/api/files/<int:identifier>/download.api", methods=["GET"], provide_automatic_options=False
)
def download_api(identifier: int) -> Response:
    return _download(identifier, media_type=API_MEDIA_TYPE)
