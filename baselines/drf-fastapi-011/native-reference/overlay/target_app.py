from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlencode

os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from sales.models import Account, Transaction  # noqa: E402

app = FastAPI(title="Native FastAPI aggregate reference")
REQUEST_BODY = Body(...)
ORDERING_FIELDS = {
    "code",
    "name",
    "posted_total",
    "transaction_count",
    "pending_count",
}


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def _account_metric(account: Account) -> dict[str, Any]:
    transactions = list(Transaction.objects.filter(account=account).order_by("-id"))
    posted_total = sum(
        (item.amount for item in transactions if item.state == "posted"),
        Decimal("0.00"),
    )
    pending_count = sum(item.state == "pending" for item in transactions)
    if not transactions:
        activity_state = "empty"
    elif pending_count:
        activity_state = "pending"
    else:
        activity_state = "settled"
    return {
        "id": account.id,
        "code": account.code,
        "name": account.name,
        "region": account.region,
        "transaction_count": len(transactions),
        "pending_count": pending_count,
        "posted_total": posted_total,
        "activity_state": activity_state,
        "latest_reference": transactions[0].reference if transactions else None,
    }


def _serialized_metric(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": metric["code"],
        "name": metric["name"],
        "region": metric["region"],
        "transaction_count": metric["transaction_count"],
        "pending_count": metric["pending_count"],
        "posted_total": _money(metric["posted_total"]),
        "activity_state": metric["activity_state"],
        "latest_reference": metric["latest_reference"],
    }


def _page_url(request: Request, page: int) -> str:
    pairs = [(key, value) for key, value in parse_qsl(request.url.query) if key != "page"]
    if page > 1:
        pairs.append(("page", str(page)))
    return str(request.url.replace(query=urlencode(pairs)))


@app.get("/api/accounts/")
def list_accounts(request: Request, ordering: str = "-posted_total", page: int = 1) -> Response:
    field = ordering.removeprefix("-")
    if field not in ORDERING_FIELDS:
        return JSONResponse(
            {"ordering": [f'Unsupported ordering field "{ordering}".']},
            status_code=400,
        )

    metrics = [_account_metric(account) for account in Account.objects.order_by("id")]
    tie_field = "id" if field == "code" else "code"
    metrics.sort(key=lambda metric: metric[tie_field])
    metrics.sort(key=lambda metric: metric[field], reverse=ordering.startswith("-"))

    count = len(metrics)
    start = (page - 1) * 2
    end = start + 2
    if start >= count and count:
        return JSONResponse({"detail": "Invalid page."}, status_code=404)
    results = [_serialized_metric(metric) for metric in metrics[start:end]]
    return JSONResponse(
        {
            "count": count,
            "next": _page_url(request, page + 1) if end < count else None,
            "previous": _page_url(request, page - 1) if page > 1 else None,
            "results": results,
        }
    )


@app.get("/api/summary/")
def summary() -> Response:
    groups: list[dict[str, Any]] = []
    for region in Account.objects.order_by("region").values_list("region", flat=True).distinct():
        accounts = Account.objects.filter(region=region)
        transactions = Transaction.objects.filter(account__region=region)
        posted_total = sum(
            (item.amount for item in transactions if item.state == "posted"),
            Decimal("0.00"),
        )
        groups.append(
            {
                "region": region,
                "account_count": accounts.count(),
                "transaction_count": transactions.count(),
                "posted_total": _money(posted_total),
            }
        )
    grand_total = sum(
        (item.amount for item in Transaction.objects.filter(state="posted").only("amount")),
        Decimal("0.00"),
    )
    return JSONResponse({"groups": groups, "grand_total": _money(grand_total)})


def _transaction_payload(item: Transaction) -> dict[str, Any]:
    return {
        "id": item.id,
        "account": item.account.code,
        "reference": item.reference,
        "state": item.state,
        "amount": _money(item.amount),
        "note": item.note,
    }


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed.quantize(Decimal("0.01"))


@app.post("/api/transactions/")
def create_transaction(payload: dict[str, Any] = REQUEST_BODY) -> Response:
    reference = str(payload.get("reference", "")).strip()
    if Transaction.objects.filter(reference=reference).exists():
        return JSONResponse(
            {"reference": ["transaction with this reference already exists."]},
            status_code=400,
        )
    account = Account.objects.filter(code=payload.get("account")).first()
    amount = _decimal(payload.get("amount"))
    if account is None or amount is None:
        return JSONResponse({"detail": "Invalid transaction."}, status_code=400)
    item = Transaction.objects.create(
        account=account,
        reference=reference,
        state=str(payload.get("state")),
        amount=amount,
        note=str(payload.get("note", "")).strip(),
    )
    return JSONResponse(_transaction_payload(item), status_code=201)


def _get_transaction(identifier: int) -> Transaction | None:
    return Transaction.objects.select_related("account").filter(pk=identifier).first()


def _transaction_not_found() -> JSONResponse:
    return JSONResponse(
        {"detail": "No Transaction matches the given query."},
        status_code=404,
    )


@app.patch("/api/transactions/{identifier}/")
def patch_transaction(identifier: int, payload: dict[str, Any] = REQUEST_BODY) -> Response:
    item = _get_transaction(identifier)
    if item is None:
        return _transaction_not_found()
    fields: list[str] = []
    if "account" in payload:
        account = Account.objects.filter(code=payload["account"]).first()
        if account is None:
            return JSONResponse({"detail": "Invalid transaction."}, status_code=400)
        item.account = account
        fields.append("account")
    if "reference" in payload:
        item.reference = str(payload["reference"]).strip()
        fields.append("reference")
    if "state" in payload:
        item.state = str(payload["state"])
        fields.append("state")
    if "amount" in payload:
        amount = _decimal(payload["amount"])
        if amount is None:
            return JSONResponse({"detail": "Invalid transaction."}, status_code=400)
        item.amount = amount
        fields.append("amount")
    if "note" in payload:
        item.note = str(payload["note"]).strip()
        fields.append("note")
    if fields:
        item.save(update_fields=fields)
    return JSONResponse(_transaction_payload(item))


@app.delete("/api/transactions/{identifier}/")
def delete_transaction(identifier: int) -> Response:
    item = _get_transaction(identifier)
    if item is None:
        return _transaction_not_found()
    item.delete()
    return Response(status_code=204)
