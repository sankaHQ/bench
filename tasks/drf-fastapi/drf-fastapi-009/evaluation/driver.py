from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sanka_bench.workspace_effects import workspace_changes, workspace_snapshot

GUARD_TIMEOUT_SECONDS = 90


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("source", "candidate"), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--policy", default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    workspace = args.workspace.resolve()
    effects_before = workspace_snapshot(workspace)
    database = args.database.resolve()
    media_root = database.with_name(f"{database.stem}-media")
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True)

    sys.path.insert(0, str(workspace))
    os.environ["DJANGO_SETTINGS_MODULE"] = "files_project.settings"
    os.environ["BENCH_DB_PATH"] = str(database)
    os.environ["BENCH_MEDIA_ROOT"] = str(media_root)

    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    _seed_database(media_root)

    scenario: dict[str, Any] = json.loads(args.scenario)
    requests = [*_setup_requests(scenario), scenario]
    if args.mode == "source":
        served = _source_requests(requests)
    else:
        if args.policy is None:
            print("candidate mode requires --policy", file=sys.stderr)
            return 2
        served = _guarded_candidate_requests(workspace, scenario, requests, args.policy)

    payload = dict(served)
    payload["database"] = _database_state()
    payload["side_effects"] = _media_state(media_root) + workspace_changes(
        effects_before, workspace_snapshot(workspace)
    )
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


def _seed_database(media_root: Path) -> None:
    from artifacts.models import Artifact

    Artifact.objects.all().delete()
    fixtures = [
        (1, "guide", "Migration guide", "guide.txt", "text/plain", b"alpha\r\nbeta\n"),
        (
            2,
            "config",
            "Safe config",
            "config.json",
            "application/json",
            b'{"mode":"safe"}\n',
        ),
    ]
    uploads = media_root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    for identifier, key, label, name, content_type, content in fixtures:
        relative = f"uploads/{name}"
        (media_root / relative).write_bytes(content)
        Artifact.objects.create(
            id=identifier,
            key=key,
            label=label,
            file=relative,
            original_name=name,
            content_type=content_type,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )


def _database_state() -> dict[str, Any]:
    from artifacts.models import Artifact
    from django.db import connection

    rows = list(
        Artifact.objects.order_by("id").values(
            "id",
            "key",
            "label",
            "file",
            "original_name",
            "content_type",
            "byte_size",
            "sha256",
        )
    )
    for row in rows:
        row["file"] = str(row["file"])
    connection.close()
    return {"artifacts": rows}


def _media_state(media_root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(media_root.rglob("*")):
        if not path.is_file():
            continue
        content = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(media_root).as_posix(),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_b64": base64.b64encode(content).decode("ascii"),
            }
        )
    return files


def _setup_requests(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    setup = scenario.get("setup") or []
    if not isinstance(setup, list):
        print("scenario setup must be a list of requests", file=sys.stderr)
        raise SystemExit(2)
    return [dict(request) for request in setup]


def _source_requests(requests: list[dict[str, Any]]) -> dict[str, Any]:
    from django.test import Client

    client = Client()
    responses = [_source_request(client, _materialize(request)) for request in requests]
    return _response_payload(responses)


def _source_request(client: Any, request: dict[str, Any]) -> dict[str, Any]:
    headers = {str(key): str(value) for key, value in request.get("headers", {}).items()}
    multipart = request.get("multipart")
    if isinstance(multipart, dict):
        body, boundary = _multipart_body(multipart)
        response = client.generic(
            str(request["method"]),
            str(request["path"]),
            data=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            headers=headers,
        )
    else:
        body = request.get("body")
        response = client.generic(
            str(request["method"]),
            str(request["path"]),
            data=json.dumps(body) if body is not None else "",
            content_type="application/json",
            headers=headers,
        )
    content = (
        b"".join(response.streaming_content)
        if getattr(response, "streaming", False)
        else bytes(response.content)
    )
    served: dict[str, Any] = {
        "status": response.status_code,
        "body": _body(content, request),
    }
    capture = request.get("capture_headers")
    if capture:
        served["headers"] = {str(name).lower(): str(response.get(name, "")) for name in capture}
    return served


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
                str(value).encode(),
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


def _guarded_candidate_requests(
    workspace: Path,
    scenario: dict[str, Any],
    requests: list[dict[str, Any]],
    policy: str,
) -> dict[str, Any]:
    responses: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        materialized = _materialize(request)
        materialized["id"] = f"{scenario['id']}#{index}"
        served = _guarded_candidate_request(workspace, materialized, policy)
        response = served.get("response")
        if not isinstance(response, dict):
            print("guarded serving process returned no response object", file=sys.stderr)
            raise SystemExit(1)
        responses.append(response)
        native = served.get("native")
        if isinstance(native, dict):
            evidences.append(native)
    payload = _response_payload(responses)
    if evidences:
        payload["native"] = _merge_native(evidences)
    return payload


def _materialize(template: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in template.items() if key not in {"id", "setup"}}


def _response_payload(responses: list[dict[str, Any]]) -> dict[str, Any]:
    response = responses[-1]
    if len(responses) > 1:
        response = {**response, "setup": responses[:-1]}
    return {"response": response}


def _guarded_candidate_request(
    workspace: Path, request_scenario: dict[str, Any], policy: str
) -> dict[str, Any]:
    parsed = json.loads(policy)
    child_env = {key: value for key, value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"}
    outcome = subprocess.run(
        [
            sys.executable,
            "-m",
            "sanka_bench.serving_guard",
            "--workspace",
            str(workspace),
            "--entrypoint",
            str(parsed["entrypoint"]),
            "--scenario",
            json.dumps(request_scenario, ensure_ascii=False, separators=(",", ":")),
            "--forbidden-imports",
            json.dumps(parsed["forbidden_imports"], ensure_ascii=False, separators=(",", ":")),
        ],
        cwd=workspace,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=GUARD_TIMEOUT_SECONDS,
        check=False,
    )
    if outcome.returncode != 0:
        detail = outcome.stderr.strip() or outcome.stdout.strip() or "no output"
        print(f"guarded serving process exited {outcome.returncode}: {detail}", file=sys.stderr)
        raise SystemExit(outcome.returncode or 1)
    lines = [line for line in outcome.stdout.splitlines() if line.strip()]
    if not lines:
        print("guarded serving process returned no JSON", file=sys.stderr)
        raise SystemExit(1)
    served = json.loads(lines[-1])
    if not isinstance(served, dict):
        print("guarded serving process must return an object", file=sys.stderr)
        raise SystemExit(1)
    return served


def _merge_native(evidences: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(evidences[-1])
    merged["app_is_fastapi"] = all(bool(evidence.get("app_is_fastapi")) for evidence in evidences)
    merged["endpoint_in_workspace"] = all(
        bool(evidence.get("endpoint_in_workspace")) for evidence in evidences
    )
    if any(evidence.get("route_class") is None for evidence in evidences):
        merged["route_class"] = None
    else:
        classes = sorted({str(evidence["route_class"]) for evidence in evidences})
        merged["route_class"] = classes[0] if len(classes) == 1 else "; ".join(classes)
    for key in ("forbidden_imports", "process_events", "socket_events"):
        merged[key] = sorted({item for evidence in evidences for item in evidence.get(key) or []})
    return merged


def _body(content: bytes, request: dict[str, Any]) -> Any:
    if not content:
        return None
    if request.get("response_body") == "base64":
        return {"base64": base64.b64encode(content).decode("ascii")}
    try:
        return json.loads(content)
    except (ValueError, json.JSONDecodeError):
        try:
            return content.decode()
        except UnicodeDecodeError:
            return {"base64": base64.b64encode(content).decode("ascii")}


if __name__ == "__main__":
    raise SystemExit(main())
