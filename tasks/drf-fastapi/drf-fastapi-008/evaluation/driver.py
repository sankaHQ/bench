from __future__ import annotations

import argparse
import json
import os
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
    sys.path.insert(0, str(workspace))
    os.environ["DJANGO_SETTINGS_MODULE"] = "legacy_project.settings"
    os.environ["BENCH_DB_PATH"] = str(args.database.resolve())

    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    _seed_database()

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
    payload["side_effects"] = workspace_changes(effects_before, workspace_snapshot(workspace))
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


def _seed_database() -> None:
    from catalog.models import Entry

    Entry.objects.all().delete()
    Entry.objects.bulk_create(
        [
            Entry(
                id=1,
                code="guide.v2+draft",
                title="Migration guide",
                body="Shared legacy record",
                state="draft",
            ),
            Entry(
                id=2,
                code="release@2026.08",
                title="Release notes",
                body="Published record",
                state="published",
            ),
        ]
    )


def _database_state() -> dict[str, Any]:
    from catalog.models import Entry
    from django.db import connection

    rows = list(Entry.objects.order_by("id").values("id", "code", "title", "body", "state"))
    connection.close()
    return {"entries": rows}


def _setup_requests(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    setup = scenario.get("setup") or []
    if not isinstance(setup, list):
        print("scenario setup must be a list of requests", file=sys.stderr)
        raise SystemExit(2)
    return [dict(request) for request in setup]


def _source_requests(requests: list[dict[str, Any]]) -> dict[str, Any]:
    from django.test import Client

    client = Client()
    responses: list[dict[str, Any]] = []
    for request in requests:
        responses.append(_source_request(client, _materialize(request)))
    return _response_payload(responses)


def _source_request(client: Any, request: dict[str, Any]) -> dict[str, Any]:
    body = request.get("body")
    response = client.generic(
        str(request["method"]),
        str(request["path"]),
        data=json.dumps(body) if body is not None else "",
        content_type="application/json",
        headers={str(key): str(value) for key, value in request.get("headers", {}).items()},
    )
    served: dict[str, Any] = {
        "status": response.status_code,
        "body": _body(bytes(response.content)),
    }
    capture = request.get("capture_headers")
    if capture:
        served["headers"] = {str(name).lower(): str(response.get(name, "")) for name in capture}
    return served


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


def _body(content: bytes) -> Any:
    if not content:
        return None
    try:
        return json.loads(content)
    except (ValueError, json.JSONDecodeError):
        return content.decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
