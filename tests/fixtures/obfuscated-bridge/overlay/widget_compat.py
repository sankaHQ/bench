"""Hidden compatibility dispatch: forwards FastAPI requests into Django/DRF."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import django
from django.core.asgi import get_asgi_application
from fastapi import FastAPI, Request, Response

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fixture_project.settings")
django.setup()
DJANGO_APP = get_asgi_application()

_ROUTES = [
    ("/api/widgets/", ("GET", "POST")),
    ("/api/widgets/{widget_id}/", ("PATCH", "DELETE")),
]


async def _forward(request: Request) -> Response:
    body = await request.body()
    scope = dict(request.scope)
    scope["root_path"] = ""
    messages: list[dict[str, Any]] = []
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # Django keeps a disconnect listener pending while it responds; park
        # any further receive() call forever, exactly like the PR #13 bridge.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await DJANGO_APP(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return Response(content=content, status_code=start["status"])


def attach(app: FastAPI) -> FastAPI:
    for index, (path, methods) in enumerate(_ROUTES):
        for method in methods:

            async def handler(request: Request) -> Response:
                return await _forward(request)

            handler.__name__ = f"compat_{index}_{method.lower()}"
            app.add_api_route(path, handler, methods=[method], operation_id=handler.__name__)
    return app
