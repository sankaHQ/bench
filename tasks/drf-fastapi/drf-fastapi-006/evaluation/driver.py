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
    os.environ["DJANGO_SETTINGS_MODULE"] = "graph_project.settings"
    os.environ["BENCH_DB_PATH"] = str(args.database.resolve())

    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    _seed_database()

    scenario: dict[str, Any] = json.loads(args.scenario)
    if args.mode == "source":
        served = _source_request(scenario)
    else:
        if args.policy is None:
            print("candidate mode requires --policy", file=sys.stderr)
            return 2
        served = _guarded_candidate_request(workspace, args.scenario, args.policy)

    payload = dict(served)
    payload["database"] = _database_state()
    payload["side_effects"] = workspace_changes(effects_before, workspace_snapshot(workspace))
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


def _seed_database() -> None:
    from orders.models import Adjustment, Order, OrderItem

    Adjustment.objects.all().delete()
    OrderItem.objects.all().delete()
    Order.objects.all().delete()
    order = Order.objects.create(id=1, reference="ORD-100", customer_note="priority")
    first = OrderItem.objects.create(
        id=1,
        order=order,
        sku="SKU-A",
        quantity=2,
        description="alpha",
    )
    second = OrderItem.objects.create(
        id=2,
        order=order,
        sku="SKU-B",
        quantity=1,
        description="beta",
    )
    Adjustment.objects.create(
        id=1,
        item=first,
        code="DISCOUNT",
        amount="-1.50",
        note="launch",
    )
    Adjustment.objects.create(id=2, item=first, code="TAX", amount="0.95")
    Adjustment.objects.create(
        id=3,
        item=second,
        code="TAX",
        amount="0.30",
        note="regional",
    )


def _database_state() -> dict[str, Any]:
    from django.db import connection
    from orders.models import Adjustment, Order, OrderItem

    payload = {
        "orders": list(Order.objects.order_by("id").values("id", "reference", "customer_note")),
        "order_items": list(
            OrderItem.objects.order_by("id").values(
                "id", "order_id", "sku", "quantity", "description"
            )
        ),
        "adjustments": [
            {**row, "amount": str(row["amount"])}
            for row in Adjustment.objects.order_by("id").values(
                "id", "item_id", "code", "amount", "note"
            )
        ],
    }
    connection.close()
    return payload


def _source_request(scenario: dict[str, Any]) -> dict[str, Any]:
    from django.test import Client

    body = scenario.get("body")
    response = Client().generic(
        str(scenario["method"]),
        str(scenario["path"]),
        data=json.dumps(body) if body is not None else "",
        content_type="application/json",
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
