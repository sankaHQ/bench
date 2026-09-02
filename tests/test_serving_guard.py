from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_guard(
    workspace: Path,
    *,
    entrypoint: str = "svc.py",
    scenario: dict[str, Any] | None = None,
    forbidden: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sanka_bench.serving_guard",
            "--workspace",
            str(workspace),
            "--entrypoint",
            entrypoint,
            "--scenario",
            json.dumps(scenario or {"id": "ping", "method": "GET", "path": "/ping/"}),
            "--forbidden-imports",
            json.dumps(forbidden or ["rest_framework"]),
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _payload(outcome: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert outcome.returncode == 0, outcome.stderr
    lines = [line for line in outcome.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_clean_fastapi_app_produces_compliant_evidence(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        '@app.get("/ping/")\n'
        "def ping():\n"
        '    return {"ok": True}\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    assert payload["response"] == {"status": 200, "body": {"ok": True}}
    native = payload["native"]
    assert native["app_is_fastapi"] is True
    assert native["route_class"] == "fastapi.routing.APIRoute"
    assert native["endpoint_in_workspace"] is True
    assert native["forbidden_imports"] == []
    assert native["process_events"] == []
    assert native["socket_events"] == []


def test_include_router_resolves_to_the_underlying_apiroute(tmp_path: Path) -> None:
    # FastAPI >= 0.141 keeps included routers as lazy `_IncludedRouter` entries;
    # the evidence must name the APIRoute that actually serves the request.
    (tmp_path / "svc.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter()\n"
        '@router.get("/ping/")\n'
        "def ping():\n"
        '    return {"ok": True}\n'
        "app = FastAPI()\n"
        "app.include_router(router)\n",
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    assert payload["response"] == {"status": 200, "body": {"ok": True}}
    native = payload["native"]
    assert native["route_class"] == "fastapi.routing.APIRoute"
    assert native["endpoint_in_workspace"] is True
    assert native["forbidden_imports"] == []


def test_nested_prefixed_include_router_resolves_to_the_apiroute(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "inner = APIRouter()\n"
        '@inner.get("/ping/")\n'
        "def ping():\n"
        '    return {"ok": True}\n'
        "outer = APIRouter()\n"
        'outer.include_router(inner, prefix="/v1")\n'
        "app = FastAPI()\n"
        'app.include_router(outer, prefix="/api")\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path, scenario={"method": "GET", "path": "/api/v1/ping/"}))
    assert payload["response"] == {"status": 200, "body": {"ok": True}}
    native = payload["native"]
    assert native["route_class"] == "fastapi.routing.APIRoute"
    assert native["endpoint_in_workspace"] is True


def test_included_raw_starlette_route_is_still_rejected(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "from starlette.responses import JSONResponse\n"
        "async def ping(request):\n"
        '    return JSONResponse({"ok": True})\n'
        "router = APIRouter()\n"
        'router.add_route("/ping/", ping, methods=["GET"])\n'
        "app = FastAPI()\n"
        "app.include_router(router)\n",
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    native = payload["native"]
    assert native["route_class"] != "fastapi.routing.APIRoute"


def test_apiroute_subclass_is_recorded_as_an_apiroute(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import FastAPI\n"
        "from fastapi.routing import APIRoute\n"
        "class AnyMethodRoute(APIRoute):\n"
        "    pass\n"
        "app = FastAPI()\n"
        "app.router.route_class = AnyMethodRoute\n"
        '@app.get("/ping/")\n'
        "def ping():\n"
        '    return {"ok": True}\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    native = payload["native"]
    assert native["route_class"] == "svc.AnyMethodRoute"
    assert native["route_is_apiroute"] is True
    assert native["route_path"] == "/ping/"
    assert native["endpoint_in_workspace"] is True


def test_raw_starlette_route_is_not_an_apiroute(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import FastAPI\n"
        "from starlette.responses import JSONResponse\n"
        "async def ping(request):\n"
        '    return JSONResponse({"ok": True})\n'
        "app = FastAPI()\n"
        'app.add_route("/ping/", ping, methods=["GET"])\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    native = payload["native"]
    assert native["route_class"] == "starlette.routing.Route"
    assert native["route_is_apiroute"] is False
    assert native["route_path"] == "/ping/"


def test_query_string_is_excluded_from_route_matching(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import FastAPI, Request\n"
        "app = FastAPI()\n"
        '@app.get("/ping/")\n'
        "def ping(request: Request):\n"
        '    return {"search": request.query_params.get("search")}\n',
        encoding="utf-8",
    )
    payload = _payload(
        _run_guard(
            tmp_path,
            scenario={"id": "query", "method": "GET", "path": "/ping/?search=alpha"},
        )
    )
    assert payload["response"] == {"status": 200, "body": {"search": "alpha"}}
    assert payload["native"]["route_class"] == "fastapi.routing.APIRoute"
    assert payload["native"]["endpoint_in_workspace"] is True


def test_multipart_body_is_sent_with_requested_boundary(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from base64 import b64encode\n"
        "from fastapi import FastAPI, Request\n"
        "app = FastAPI()\n"
        '@app.post("/upload/")\n'
        "async def upload(request: Request):\n"
        "    body = await request.body()\n"
        "    return {\n"
        "        'content_type': request.headers['content-type'],\n"
        "        'body_b64': b64encode(body).decode('ascii'),\n"
        "    }\n",
        encoding="utf-8",
    )
    scenario = {
        "id": "multipart",
        "method": "POST",
        "path": "/upload/",
        "multipart": {
            "boundary": "Boundary-Test-42",
            "fields": {"label": "Example"},
            "files": [
                {
                    "field": "file",
                    "filename": "sample.txt",
                    "content_type": "text/plain",
                    "content_b64": "YWxwaGENCmJldGEK",
                }
            ],
        },
    }
    payload = _payload(_run_guard(tmp_path, scenario=scenario))
    response = payload["response"]
    assert response["status"] == 200
    assert response["body"]["content_type"] == ("multipart/form-data; boundary=Boundary-Test-42")
    assert response["body"]["body_b64"].startswith("LS1Cb3VuZGFyeS1UZXN0LTQy")


def test_binary_response_is_normalized_as_base64(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import FastAPI, Response\n"
        "app = FastAPI()\n"
        '@app.get("/binary/")\n'
        "def binary():\n"
        "    return Response(bytes([0, 255, 10]), media_type='application/octet-stream')\n",
        encoding="utf-8",
    )
    payload = _payload(
        _run_guard(
            tmp_path,
            scenario={
                "id": "binary",
                "method": "GET",
                "path": "/binary/",
                "response_body": "base64",
            },
        )
    )
    assert payload["response"] == {
        "status": 200,
        "body": {"base64": "AP8K"},
    }


def test_forbidden_import_is_recorded_even_when_indirect(tmp_path: Path) -> None:
    (tmp_path / "helper.py").write_text(
        'from importlib import import_module\nwave = import_module("wave")\n',
        encoding="utf-8",
    )
    (tmp_path / "svc.py").write_text(
        "import helper  # noqa: F401\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        '@app.get("/ping/")\n'
        "def ping():\n"
        '    return {"ok": True}\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path, forbidden=["wave"]))
    assert payload["native"]["forbidden_imports"] == ["wave"]


def test_lazy_forbidden_import_inside_endpoint_is_recorded(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        '@app.get("/ping/")\n'
        "def ping():\n"
        "    import wave  # noqa: F401\n"
        '    return {"ok": True}\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path, forbidden=["wave"]))
    assert payload["native"]["forbidden_imports"] == ["wave"]


def test_spawned_process_is_recorded(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "import subprocess\n"
        "import sys\n"
        "from fastapi import FastAPI\n"
        'subprocess.run([sys.executable, "-c", "pass"], check=True)\n'
        "app = FastAPI()\n"
        '@app.get("/ping/")\n'
        "def ping():\n"
        '    return {"ok": True}\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    assert "subprocess.Popen" in payload["native"]["process_events"]


def test_socket_connection_attempt_is_recorded(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "import contextlib\n"
        "import socket\n"
        "from fastapi import FastAPI\n"
        "sock = socket.socket()\n"
        "sock.settimeout(0.05)\n"
        "with contextlib.suppress(OSError):\n"
        '    sock.connect(("127.0.0.1", 9))\n'
        "sock.close()\n"
        "app = FastAPI()\n"
        '@app.get("/ping/")\n'
        "def ping():\n"
        '    return {"ok": True}\n',
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    assert payload["native"]["socket_events"] == ["socket.connect"]


def test_non_fastapi_asgi_app_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "async def app(scope, receive, send):\n"
        "    assert scope['type'] == 'http'\n"
        "    await receive()\n"
        "    await send({'type': 'http.response.start', 'status': 200, 'headers': []})\n"
        "    await send({'type': 'http.response.body', 'body': b'{\"ok\": true}'})\n",
        encoding="utf-8",
    )
    payload = _payload(_run_guard(tmp_path))
    native = payload["native"]
    assert native["app_is_fastapi"] is False
    assert native["route_class"] is None
    assert native["endpoint_in_workspace"] is False
    assert payload["response"]["status"] == 200


def test_missing_app_attribute_fails(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text("value = 1\n", encoding="utf-8")
    outcome = _run_guard(tmp_path)
    assert outcome.returncode == 3
    assert "does not expose `app`" in outcome.stderr
