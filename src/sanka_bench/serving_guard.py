"""Guarded serving process that records native-target evidence.

The evaluator must not trust a candidate's own claims about how it serves
requests. This module is executed as a fresh child process per scenario. It
arms a PEP 578 audit hook *before* any candidate code is imported, then loads
the candidate entrypoint, serves exactly one scenario through an in-process
ASGI test client, and reports both the HTTP response and the collected serving
evidence:

- every first import of a forbidden module prefix, through three layers: an
  observing meta-path finder (sees every module resolution, including
  ``importlib.import_module`` calls that bypass ``__import__``), a PEP 578
  audit hook (cannot be removed once installed), and a final ``sys.modules``
  sweep after serving;
- process-creation events (a candidate must not spawn a source server);
- socket connections (the in-process client needs none, so any connect means
  the candidate reached for an external server);
- the class of the route object that matches the scenario and whether the
  matched endpoint's code lives inside the candidate workspace.

The guard observes and records rather than blocking, so a compatibility facade
still demonstrates its behavioral parity while failing the native-target gate
on the recorded evidence.
"""

from __future__ import annotations

import argparse
import base64
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sanka-bench-serving-guard")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--forbidden-imports", required=True)
    return parser


_PROCESS_EVENTS = {
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.posix_spawn",
    "os.spawn",
    "os.system",
    "subprocess.Popen",
}
_SOCKET_EVENTS = {"socket.connect"}


def _matched_prefix(module: str, forbidden: list[str]) -> str | None:
    for prefix in forbidden:
        if module == prefix or module.startswith(prefix + "."):
            return prefix
    return None


class _ImportObserver:
    """Meta-path finder that records module resolutions without resolving.

    The ``import`` audit event only fires on the ``__import__`` path, so a
    direct ``importlib.import_module`` call would slip past the audit hook
    alone. Every import route consults ``sys.meta_path``, so this observer
    sees them all.
    """

    def __init__(self, forbidden: list[str], seen: set[str]) -> None:
        self._forbidden = forbidden
        self._seen = seen

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        prefix = _matched_prefix(fullname, self._forbidden)
        if prefix is not None:
            self._seen.add(prefix)
        return None


def _arm_recorder(forbidden: list[str]) -> dict[str, set[str]]:
    evidence: dict[str, set[str]] = {
        "forbidden_imports": set(),
        "process_events": set(),
        "socket_events": set(),
    }

    def _hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "import":
            module = args[0]
            if isinstance(module, str):
                prefix = _matched_prefix(module, forbidden)
                if prefix is not None:
                    evidence["forbidden_imports"].add(prefix)
        elif event in _PROCESS_EVENTS:
            evidence["process_events"].add(event)
        elif event in _SOCKET_EVENTS:
            evidence["socket_events"].add(event)

    sys.addaudithook(_hook)
    sys.meta_path.insert(0, _ImportObserver(forbidden, evidence["forbidden_imports"]))
    return evidence


def _sweep_loaded_modules(forbidden: list[str], seen: set[str]) -> None:
    for module in list(sys.modules):
        prefix = _matched_prefix(module, forbidden)
        if prefix is not None:
            seen.add(prefix)


def _matched_route(app: Any, method: str, path: str) -> Any:
    routes = getattr(app, "routes", None)
    if not isinstance(routes, list):
        return None
    parsed = urlsplit(path)
    scope = {
        "type": "http",
        "method": method,
        "path": parsed.path,
        "root_path": "",
        "headers": [],
        "query_string": parsed.query.encode("ascii"),
    }
    from starlette.routing import Match

    partial = None
    for route in routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return _resolve_included_router(route, scope)
        if match == Match.PARTIAL and partial is None:
            partial = route
    return _resolve_included_router(partial, scope) if partial is not None else None


def _resolve_included_router(route: Any, scope: dict[str, Any], depth: int = 0) -> Any:
    """Resolve FastAPI's lazy ``include_router`` entries to the route that serves.

    Since FastAPI 0.141 ``app.include_router(router)`` leaves a
    ``fastapi.routing._IncludedRouter`` in ``app.routes`` instead of copying the
    router's ``APIRoute`` objects. That wrapper matches the request but carries no
    endpoint, so recording it as the matched route misreported every candidate
    built the ordinary FastAPI way (a router module plus ``include_router``) as
    non-native. Walk the wrapper's effective candidates with the same scope and
    return the underlying route, recursing through nested includes. Anything
    that is not an ``_IncludedRouter`` is returned unchanged, so raw Starlette
    routes, mounts and bridges keep failing the gate exactly as before.
    """
    from starlette.routing import Match

    if route is None or depth > 16 or type(route).__qualname__ != "_IncludedRouter":
        return route
    candidates = getattr(route, "effective_candidates", None)
    if not callable(candidates):
        return route
    partial = None
    try:
        effective = list(candidates())
    except Exception:
        return route
    for candidate in effective:
        try:
            match, _ = candidate.matches(scope)
        except Exception:
            continue
        if match == Match.FULL:
            resolved = _resolve_included_router(candidate, scope, depth + 1)
            return getattr(resolved, "original_route", resolved)
        if match == Match.PARTIAL and partial is None:
            partial = candidate
    if partial is not None:
        resolved = _resolve_included_router(partial, scope, depth + 1)
        return getattr(resolved, "original_route", resolved)
    return route


def _endpoint_in_workspace(route: Any, workspace: Path) -> bool:
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return False
    try:
        unwrapped = inspect.unwrap(endpoint)
    except ValueError:
        return False
    code = getattr(unwrapped, "__code__", None)
    filename = getattr(code, "co_filename", None)
    if not isinstance(filename, str):
        return False
    try:
        return Path(filename).resolve().is_relative_to(workspace)
    except OSError:
        return False


def _class_name(value: Any) -> str | None:
    if value is None:
        return None
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _body(response: Any, scenario: dict[str, Any]) -> Any:
    content = bytes(response.content)
    if not content:
        return None
    if scenario.get("response_body") == "base64":
        return {"base64": base64.b64encode(content).decode("ascii")}
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return {"base64": base64.b64encode(content).decode("ascii")}


def _multipart_body(spec: dict[str, Any]) -> tuple[bytes, str]:
    boundary = str(spec.get("boundary") or "SankaBenchBoundary")
    boundary_bytes = boundary.encode("ascii")
    chunks: list[bytes] = []
    fields = spec.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("multipart fields must be an object")
    for name, value in fields.items():
        chunks.extend(
            [
                b"--" + boundary_bytes,
                f'Content-Disposition: form-data; name="{name}"'.encode(),
                b"",
                str(value).encode("utf-8"),
            ]
        )
    files = spec.get("files") or []
    if not isinstance(files, list):
        raise ValueError("multipart files must be an array")
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("multipart file entries must be objects")
        name = str(item["field"])
        filename = str(item["filename"])
        content_type = str(item.get("content_type") or "application/octet-stream")
        content = base64.b64decode(str(item["content_b64"]), validate=True)
        chunks.extend(
            [
                b"--" + boundary_bytes,
                (f'Content-Disposition: form-data; name="{name}"; filename="{filename}"').encode(),
                f"Content-Type: {content_type}".encode("ascii"),
                b"",
                content,
            ]
        )
    chunks.extend([b"--" + boundary_bytes + b"--", b""])
    return b"\r\n".join(chunks), boundary


def main() -> int:
    args = _parser().parse_args()
    workspace = args.workspace.resolve()
    scenario: dict[str, Any] = json.loads(args.scenario)
    forbidden = json.loads(args.forbidden_imports)
    if not isinstance(forbidden, list) or not all(isinstance(p, str) for p in forbidden):
        print("forbidden-imports must be a JSON array of module prefixes", file=sys.stderr)
        return 2

    # Arm the un-removable recorder before anything non-stdlib is imported.
    evidence = _arm_recorder(forbidden)
    sys.path.insert(0, str(workspace))

    import fastapi
    from fastapi.testclient import TestClient

    module_name = Path(args.entrypoint).stem
    module = importlib.import_module(module_name)
    app = getattr(module, "app", None)
    if app is None:
        print(f"candidate entrypoint {args.entrypoint} does not expose `app`", file=sys.stderr)
        return 3

    method = str(scenario["method"])
    path = str(scenario["path"])
    from fastapi.routing import APIRoute

    route = _matched_route(app, method, path)
    route_path = getattr(route, "path", None) if route is not None else None
    native: dict[str, Any] = {
        "app_is_fastapi": isinstance(app, fastapi.FastAPI),
        # The concrete class stays in the evidence for reviewers; the gate itself
        # accepts any APIRoute subclass whose endpoint lives in the workspace.
        "route_class": _class_name(route),
        "route_is_apiroute": isinstance(route, APIRoute),
        "route_path": route_path if isinstance(route_path, str) else None,
        "endpoint_in_workspace": route is not None and _endpoint_in_workspace(route, workspace),
    }

    client = TestClient(app, follow_redirects=False)
    headers = {str(key): str(value) for key, value in dict(scenario.get("headers") or {}).items()}
    multipart = scenario.get("multipart")
    if isinstance(multipart, dict):
        content, boundary = _multipart_body(multipart)
        headers.setdefault("content-type", f"multipart/form-data; boundary={boundary}")
        response = client.request(method, path, content=content, headers=headers)
    else:
        response = client.request(method, path, json=scenario.get("body"), headers=headers)

    import os

    _sweep_loaded_modules(forbidden, evidence["forbidden_imports"])
    native.update(
        {
            "forbidden_imports": sorted(evidence["forbidden_imports"]),
            "process_events": sorted(evidence["process_events"]),
            "socket_events": sorted(evidence["socket_events"]),
            "settings_module": os.environ.get("DJANGO_SETTINGS_MODULE"),
        }
    )
    served: dict[str, Any] = {
        "status": response.status_code,
        "body": _body(response, scenario),
    }
    capture = scenario.get("capture_headers")
    if capture:
        served["headers"] = {
            str(name).lower(): response.headers.get(str(name).lower(), "") for name in capture
        }
    payload = {
        "response": served,
        "native": native,
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
