from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

# The serving process owns its configuration: Django keeps only the ORM half,
# and the ledger app is installed without its signal receivers. Every side
# effect the source application delegated to signals is applied explicitly
# below, inside the same transaction as the write that causes it.
os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import F  # noqa: E402
from ledger.models import Account, AuditLog, LedgerEntry  # noqa: E402

TWO_PLACES = Decimal("0.01")
DECIMAL_TAIL = re.compile(r"\.0*\s*$")

app = FastAPI(title="Native FastAPI ledger service")


# ---------------------------------------------------------------------------
# Side effects (the source application runs these from Django signals)
# ---------------------------------------------------------------------------


def _post_entry_created(entry: LedgerEntry) -> None:
    Account.objects.filter(pk=entry.account_id).update(balance=F("balance") + entry.amount)
    AuditLog.objects.create(action="entry-created", account_id=entry.account_id, delta=entry.amount)


def _post_entry_deleted(account_id: int, amount: Decimal) -> None:
    Account.objects.filter(pk=account_id).update(balance=F("balance") - amount)
    AuditLog.objects.create(action="entry-deleted", account_id=account_id, delta=-amount)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _decimal_repr(value: Any) -> str:
    return str(Decimal(value).quantize(TWO_PLACES))


def _serialize_account(account: Account) -> dict[str, Any]:
    return {"id": account.id, "name": account.name, "balance": _decimal_repr(account.balance)}


def _serialize_entry(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "account": entry.account_id,
        "amount": _decimal_repr(entry.amount),
        "memo": entry.memo,
    }


def _serialize_audit(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "action": row.action,
        "account_id": row.account_id,
        "delta": _decimal_repr(row.delta),
    }


# ---------------------------------------------------------------------------
# Validation (native reimplementation of the DRF serializer semantics)
# ---------------------------------------------------------------------------


def _clean_char(value: Any, *, max_length: int, allow_blank: bool) -> tuple[Any, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if value == "" or (isinstance(value, str) and not value.strip()):
        if allow_blank:
            return "", []
        return None, ["This field may not be blank."]
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None, ["Not a valid string."]
    cleaned = str(value).strip()
    if len(cleaned) > max_length:
        return None, [f"Ensure this field has no more than {max_length} characters."]
    return cleaned, []


def _clean_integer(value: Any) -> tuple[Any, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if isinstance(value, str) and len(value) > 1000:
        return None, ["String value too large."]
    try:
        cleaned = int(DECIMAL_TAIL.sub("", str(value).strip()))
    except (TypeError, ValueError):
        return None, ["A valid integer is required."]
    return cleaned, []


def _clean_decimal(value: Any, *, min_value: Decimal | None = None) -> tuple[Any, list[str]]:
    if value is None:
        return None, ["This field may not be null."]
    if isinstance(value, bool):
        return None, ["A valid number is required."]
    try:
        cleaned = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None, ["A valid number is required."]
    if cleaned.is_nan() or cleaned.is_infinite():
        return None, ["A valid number is required."]
    _sign, digittuple, exponent = cleaned.as_tuple()
    if not isinstance(exponent, int):
        return None, ["A valid number is required."]
    if exponent >= 0:
        digits = len(digittuple) + exponent
        decimals = 0
    elif abs(exponent) > len(digittuple):
        digits = decimals = abs(exponent)
    else:
        digits = len(digittuple)
        decimals = abs(exponent)
    whole_digits = digits - decimals
    if digits > 12:
        return None, ["Ensure that there are no more than 12 digits in total."]
    if decimals > 2:
        return None, ["Ensure that there are no more than 2 decimal places."]
    if whole_digits > 10:
        return None, ["Ensure that there are no more than 10 digits before the decimal point."]
    if min_value is not None and cleaned < min_value:
        return None, [f"Ensure this value is greater than or equal to {min_value}."]
    return cleaned, []


def _validate_account_payload(
    payload: Any, *, partial: bool, current: Account | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        type_name = type(payload).__name__
        message = f"Invalid data. Expected a dictionary, but got {type_name}."
        return {}, {"non_field_errors": [message]}
    errors: dict[str, Any] = {}
    validated: dict[str, Any] = {}
    # `balance` and `id` are read-only fields: silently ignored on write.
    if "name" not in payload:
        if not partial:
            errors["name"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_char(payload["name"], max_length=60, allow_blank=False)
        if field_errors:
            errors["name"] = field_errors
        else:
            existing = Account.objects.filter(name=cleaned)
            if current is not None:
                existing = existing.exclude(pk=current.pk)
            if existing.exists():
                errors["name"] = ["account with this name already exists."]
            else:
                validated["name"] = cleaned
    return validated, errors


def _validate_entry_payload(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        type_name = type(payload).__name__
        message = f"Invalid data. Expected a dictionary, but got {type_name}."
        return {}, {"non_field_errors": [message]}
    errors: dict[str, Any] = {}
    validated: dict[str, Any] = {}
    if "account" not in payload:
        errors["account"] = ["This field is required."]
    else:
        raw = payload["account"]
        if raw is None:
            errors["account"] = ["This field may not be null."]
        elif isinstance(raw, bool):
            errors["account"] = ["Incorrect type. Expected pk value, received bool."]
        else:
            try:
                validated["account"] = Account.objects.get(pk=raw)
            except Account.DoesNotExist:
                errors["account"] = [f'Invalid pk "{raw}" - object does not exist.']
            except (TypeError, ValueError):
                type_name = type(raw).__name__
                errors["account"] = [f"Incorrect type. Expected pk value, received {type_name}."]
    if "amount" not in payload:
        errors["amount"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_decimal(payload["amount"])
        if field_errors:
            errors["amount"] = field_errors
        else:
            validated["amount"] = cleaned
    if "memo" in payload:
        cleaned, field_errors = _clean_char(payload["memo"], max_length=120, allow_blank=True)
        if field_errors:
            errors["memo"] = field_errors
        else:
            validated["memo"] = cleaned
    else:
        validated["memo"] = ""
    return validated, errors


def _validate_transfer_payload(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        type_name = type(payload).__name__
        message = f"Invalid data. Expected a dictionary, but got {type_name}."
        return {}, {"non_field_errors": [message]}
    errors: dict[str, Any] = {}
    validated: dict[str, Any] = {}
    if "target" not in payload:
        errors["target"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_integer(payload["target"])
        if field_errors:
            errors["target"] = field_errors
        else:
            validated["target"] = cleaned
    if "amount" not in payload:
        errors["amount"] = ["This field is required."]
    else:
        cleaned, field_errors = _clean_decimal(payload["amount"], min_value=Decimal("0.01"))
        if field_errors:
            errors["amount"] = field_errors
        else:
            validated["amount"] = cleaned
    return validated, errors


# ---------------------------------------------------------------------------
# Request plumbing
# ---------------------------------------------------------------------------


async def _read_raw_body(request: Request) -> bytes:
    return await request.body()


def _parse_json(raw: bytes) -> tuple[Any, Response | None]:
    if not raw:
        return {}, None
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, JSONResponse({"detail": f"JSON parse error - {exc}"}, status_code=400)


def _not_found(model_name: str, cause: str) -> Response:
    detail = f"No {model_name} matches the given query." if cause == "missing" else "Not found."
    return JSONResponse({"detail": detail}, status_code=404)


def _get_account(request: Request) -> tuple[Account | None, str]:
    raw = request.path_params.get("pk")
    try:
        return Account.objects.get(pk=raw), ""
    except Account.DoesNotExist:
        return None, "missing"
    except (TypeError, ValueError, OverflowError):
        return None, "invalid"


def _get_entry(request: Request) -> tuple[LedgerEntry | None, str]:
    raw = request.path_params.get("pk")
    try:
        return LedgerEntry.objects.get(pk=raw), ""
    except LedgerEntry.DoesNotExist:
        return None, "missing"
    except (TypeError, ValueError, OverflowError):
        return None, "invalid"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


@app.get("/api/accounts/")
def list_accounts(request: Request) -> Response:
    payload = [_serialize_account(account) for account in Account.objects.order_by("id")]
    return JSONResponse(payload)


@app.post("/api/accounts/")
def create_account(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    payload, parse_error = _parse_json(raw_body)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate_account_payload(payload, partial=False, current=None)
    if errors:
        return JSONResponse(errors, status_code=400)
    account = Account.objects.create(**validated)
    return JSONResponse(_serialize_account(account), status_code=201)


@app.get("/api/accounts/{pk}/")
def retrieve_account(request: Request) -> Response:
    account, miss = _get_account(request)
    if account is None:
        return _not_found("Account", miss)
    return JSONResponse(_serialize_account(account))


def _mutate_account(request: Request, raw_body: bytes, *, partial: bool) -> Response:
    account, miss = _get_account(request)
    if account is None:
        return _not_found("Account", miss)
    payload, parse_error = _parse_json(raw_body)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate_account_payload(payload, partial=partial, current=account)
    if errors:
        return JSONResponse(errors, status_code=400)
    for name, value in validated.items():
        setattr(account, name, value)
    account.save()
    return JSONResponse(_serialize_account(account))


@app.put("/api/accounts/{pk}/")
def update_account(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    return _mutate_account(request, raw_body, partial=False)


@app.patch("/api/accounts/{pk}/")
def partial_update_account(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    return _mutate_account(request, raw_body, partial=True)


@app.delete("/api/accounts/{pk}/")
def destroy_account(request: Request) -> Response:
    account, miss = _get_account(request)
    if account is None:
        return _not_found("Account", miss)
    with transaction.atomic():
        # Django's deletion collector removes the cascaded entries in one
        # batch, then fires post_delete per instance in descending pk order.
        entries = list(account.entries.order_by("-id"))
        account.entries.all().delete()
        for entry in entries:
            _post_entry_deleted(entry.account_id, entry.amount)
        account.delete()
    return Response(status_code=204)


@app.post("/api/accounts/{pk}/transfer/")
def transfer(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    account, miss = _get_account(request)
    if account is None:
        return _not_found("Account", miss)
    payload, parse_error = _parse_json(raw_body)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate_transfer_payload(payload)
    if errors:
        return JSONResponse(errors, status_code=400)
    target_pk = validated["target"]
    amount = validated["amount"]
    with transaction.atomic():
        locked = {
            row.pk: row
            for row in Account.objects.select_for_update()
            .filter(pk__in={account.pk, target_pk})
            .order_by("pk")
        }
        source_account = locked[account.pk]
        target_account = locked.get(target_pk)
        if target_account is None:
            return JSONResponse({"target": ["Target account not found."]}, status_code=400)
        if source_account.balance < amount:
            return JSONResponse({"amount": ["Insufficient funds."]}, status_code=400)
        out_entry = LedgerEntry.objects.create(
            account=source_account, amount=-amount, memo="transfer-out"
        )
        _post_entry_created(out_entry)
        in_entry = LedgerEntry.objects.create(
            account=target_account, amount=amount, memo="transfer-in"
        )
        _post_entry_created(in_entry)
        AuditLog.objects.create(action="transfer", account_id=source_account.pk, delta=amount)
    source_account.refresh_from_db()
    return JSONResponse(_serialize_account(source_account))


# ---------------------------------------------------------------------------
# Ledger entries
# ---------------------------------------------------------------------------


@app.get("/api/entries/")
def list_entries(request: Request) -> Response:
    payload = [_serialize_entry(entry) for entry in LedgerEntry.objects.order_by("id")]
    return JSONResponse(payload)


@app.post("/api/entries/")
def create_entry(request: Request, raw_body: bytes = Depends(_read_raw_body)) -> Response:
    payload, parse_error = _parse_json(raw_body)
    if parse_error is not None:
        return parse_error
    validated, errors = _validate_entry_payload(payload)
    if errors:
        return JSONResponse(errors, status_code=400)
    with transaction.atomic():
        entry = LedgerEntry.objects.create(
            account=validated["account"], amount=validated["amount"], memo=validated["memo"]
        )
        _post_entry_created(entry)
    return JSONResponse(_serialize_entry(entry), status_code=201)


@app.get("/api/entries/{pk}/")
def retrieve_entry(request: Request) -> Response:
    entry, miss = _get_entry(request)
    if entry is None:
        return _not_found("LedgerEntry", miss)
    return JSONResponse(_serialize_entry(entry))


@app.delete("/api/entries/{pk}/")
def destroy_entry(request: Request) -> Response:
    entry, miss = _get_entry(request)
    if entry is None:
        return _not_found("LedgerEntry", miss)
    with transaction.atomic():
        account_id, amount = entry.account_id, entry.amount
        entry.delete()
        _post_entry_deleted(account_id, amount)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Audit log (read-only)
# ---------------------------------------------------------------------------


@app.get("/api/audit/")
def list_audit(request: Request) -> Response:
    payload = [_serialize_audit(row) for row in AuditLog.objects.order_by("id")]
    return JSONResponse(payload)
