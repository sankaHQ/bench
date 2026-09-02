from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from sanka_bench.workspace_effects import workspace_changes, workspace_snapshot

GUARD_TIMEOUT_SECONDS = 90

ALICE_TOKEN = "a" * 40
BOB_TOKEN = "b" * 40
ADMIN_TOKEN = "d" * 40
EXPIRED_TOKEN = "e" * 40
INACTIVE_TOKEN = "i" * 40
BOB_SESSION = "s" * 32
ADMIN_SESSION = "t" * 32


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
    os.environ["DJANGO_SETTINGS_MODULE"] = "access_project.settings"
    os.environ["BENCH_DB_PATH"] = str(args.database.resolve())

    import django

    django.setup()
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
    from django.contrib.auth.models import User
    from django.contrib.sessions.backends.db import SessionStore
    from django.contrib.sessions.models import Session
    from django.core.management import call_command
    from django.utils import timezone
    from documents.models import AccessToken, Document

    call_command("migrate", interactive=False, verbosity=0)

    Document.objects.all().delete()
    AccessToken.objects.all().delete()
    Session.objects.all().delete()
    User.objects.all().delete()
    alice = User.objects.create(id=1, username="alice", is_active=True)
    bob = User.objects.create(id=2, username="bob", is_active=True)
    admin = User.objects.create(id=3, username="admin", is_active=True, is_staff=True)
    inactive = User.objects.create(id=4, username="inactive", is_active=False)
    future = timezone.now() + timedelta(days=30)
    AccessToken.objects.bulk_create(
        [
            AccessToken(key=ALICE_TOKEN, user=alice, expires_at=future),
            AccessToken(key=BOB_TOKEN, user=bob, expires_at=future),
            AccessToken(key=ADMIN_TOKEN, user=admin, expires_at=future),
            AccessToken(
                key=EXPIRED_TOKEN,
                user=alice,
                expires_at=timezone.now() - timedelta(days=1),
            ),
            AccessToken(key=INACTIVE_TOKEN, user=inactive, expires_at=future),
        ]
    )
    _create_session(
        SessionStore, bob, BOB_SESSION, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
    )
    _create_session(
        SessionStore,
        admin,
        ADMIN_SESSION,
        SESSION_KEY,
        BACKEND_SESSION_KEY,
        HASH_SESSION_KEY,
    )
    Document.objects.create(
        id=1,
        owner=alice,
        title="Alpha document",
        body="alice-private",
        reviewed=False,
    )
    Document.objects.create(
        id=2,
        owner=bob,
        title="Beta document",
        body="bob-private",
        reviewed=False,
    )
    Document.objects.create(
        id=3,
        owner=admin,
        title="Operations document",
        body="staff-owned",
        reviewed=True,
    )

    scenario: dict[str, Any] = json.loads(args.scenario)

    if args.mode == "source":
        served = _source_request(scenario)
    else:
        if args.policy is None:
            print("candidate mode requires --policy", file=sys.stderr)
            return 2
        served = _guarded_candidate_request(workspace, args.scenario, args.policy)

    from django.db import connection

    connection.close()
    payload = dict(served)
    payload["database"] = {
        "documents": list(
            Document.objects.order_by("id").values("id", "owner_id", "title", "body", "reviewed")
        )
    }
    payload["side_effects"] = workspace_changes(effects_before, workspace_snapshot(workspace))
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


def _create_session(
    store_class: Any,
    user: Any,
    session_key: str,
    user_key: str,
    backend_key: str,
    hash_key: str,
) -> None:
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    store = store_class()
    session_data = store.encode(
        {
            user_key: str(user.pk),
            backend_key: "django.contrib.auth.backends.ModelBackend",
            hash_key: user.get_session_auth_hash(),
        }
    )
    Session.objects.create(
        session_key=session_key,
        session_data=session_data,
        expire_date=timezone.now() + timedelta(days=30),
    )


def _source_request(scenario: dict[str, Any]) -> dict[str, Any]:
    from django.test import Client

    body = scenario.get("body")
    headers = {str(key): str(value) for key, value in dict(scenario.get("headers") or {}).items()}
    django_headers = {
        "HTTP_" + key.upper().replace("-", "_"): value for key, value in headers.items()
    }
    client = Client(enforce_csrf_checks=True)
    response = client.generic(
        str(scenario["method"]),
        str(scenario["path"]),
        data=json.dumps(body) if body is not None else "",
        content_type="application/json",
        **django_headers,
    )
    served: dict[str, Any] = {
        "status": response.status_code,
        "body": _body(bytes(response.content)),
    }
    capture = scenario.get("capture_headers")
    if capture:
        served["headers"] = {str(name).lower(): str(response.get(name, "")) for name in capture}
    return {"response": served}


def _guarded_candidate_request(workspace: Path, scenario: str, policy: str) -> dict[str, Any]:
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
            scenario,
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


def _body(content: bytes) -> Any:
    if not content:
        return None
    try:
        return json.loads(content)
    except (ValueError, json.JSONDecodeError):
        return content.decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
