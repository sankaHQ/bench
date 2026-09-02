from __future__ import annotations

import hashlib
import json
import os
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib import parse
from zoneinfo import ZoneInfo

os.environ["DJANGO_SETTINGS_MODULE"] = "target_settings"

import django
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, Response

django.setup()

from django.db.models import Q, QuerySet  # noqa: E402
from records.models import Record  # noqa: E402

app = FastAPI(title="Native FastAPI response-precision reference")
TOKYO = ZoneInfo("Asia/Tokyo")
PAGE_SIZE = 2
VALID_ORDERING = {"amount", "posted_at", "label"}
DEFAULT_ORDERING = ("-posted_at", "-id")
DETAIL_HEADERS = {"Cache-Control": "private, max-age=0", "Vary": "Accept"}
REQUEST_BODY = Body(...)


@dataclass(frozen=True)
class Cursor:
    offset: int
    reverse: bool
    position: str | None


@dataclass
class Page:
    base_url: str
    cursor: Cursor | None
    ordering: tuple[str, ...]
    records: list[Record]
    has_next: bool
    has_previous: bool
    next_position: str | None = None
    previous_position: str | None = None


def _decimal_repr(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _serialize(record: Record) -> dict[str, Any]:
    return {
        "id": record.id,
        "label": record.label,
        "category": record.category,
        "amount": _decimal_repr(record.amount),
        "posted_at": record.posted_at.astimezone(TOKYO).isoformat(timespec="seconds"),
    }


def _etag(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f'"{hashlib.sha256(canonical).hexdigest()}"'


def _without_content_length(response: Response) -> Response:
    response.raw_headers = [
        (name, value) for name, value in response.raw_headers if name.lower() != b"content-length"
    ]
    return response


def _detail_response(request: Request, payload: dict[str, Any], status_code: int = 200) -> Response:
    etag = _etag(payload)
    headers = {**DETAIL_HEADERS, "ETag": etag}
    supplied = request.headers.get("if-none-match", "")
    if any(candidate.strip() in {"*", etag} for candidate in supplied.split(",")):
        return Response(status_code=304, headers=headers)
    return _without_content_length(JSONResponse(payload, status_code=status_code, headers=headers))


def _ordering(request: Request) -> tuple[str, ...]:
    raw = request.query_params.get("ordering")
    if not raw:
        return DEFAULT_ORDERING
    requested = [term.strip() for term in raw.split(",")]
    accepted = [term for term in requested if term.removeprefix("-") in VALID_ORDERING]
    if not accepted:
        return DEFAULT_ORDERING
    if "id" not in {term.removeprefix("-") for term in accepted}:
        accepted.append("-id" if accepted[-1].startswith("-") else "id")
    return tuple(accepted)


def _filtered(request: Request) -> QuerySet[Record]:
    queryset = Record.objects.all()
    raw = request.query_params.get("search", "")
    terms = [term for term in raw.split() if term]
    for term in terms:
        queryset = queryset.filter(Q(label__icontains=term) | Q(category__icontains=term))
    return queryset


def _reverse_ordering(ordering: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term[1:] if term.startswith("-") else f"-{term}" for term in ordering)


def _position(record: Record, ordering: tuple[str, ...]) -> str:
    return str(getattr(record, ordering[0].removeprefix("-")))


def _decode_cursor(request: Request) -> Cursor | None:
    encoded = request.query_params.get("cursor")
    if encoded is None:
        return None
    try:
        querystring = b64decode(encoded.encode("ascii")).decode("ascii")
        tokens = parse.parse_qs(querystring, keep_blank_values=True)
        offset = int(tokens.get("o", ["0"])[0])
        if offset < 0:
            raise ValueError
        offset = min(offset, 1000)
        reverse = bool(int(tokens.get("r", ["0"])[0]))
        position = tokens.get("p", [None])[0]
    except (TypeError, ValueError):
        raise ValueError("Invalid cursor") from None
    return Cursor(offset=offset, reverse=reverse, position=position)


def _replace_query_param(url: str, key: str, value: str) -> str:
    scheme, netloc, path, query, fragment = parse.urlsplit(url)
    query_dict = parse.parse_qs(query, keep_blank_values=True)
    query_dict[key] = [value]
    query = parse.urlencode(sorted(query_dict.items()), doseq=True)
    return parse.urlunsplit((scheme, netloc, path, query, fragment))


def _encode_cursor(page: Page, cursor: Cursor) -> str:
    tokens: dict[str, str] = {}
    if cursor.offset:
        tokens["o"] = str(cursor.offset)
    if cursor.reverse:
        tokens["r"] = "1"
    if cursor.position is not None:
        tokens["p"] = cursor.position
    querystring = parse.urlencode(tokens, doseq=True)
    encoded = b64encode(querystring.encode("ascii")).decode("ascii")
    return _replace_query_param(page.base_url, "cursor", encoded)


def _paginate(queryset: QuerySet[Record], request: Request) -> Page:
    ordering = _ordering(request)
    cursor = _decode_cursor(request)
    offset, reverse, current_position = (0, False, None)
    if cursor is not None:
        offset, reverse, current_position = cursor.offset, cursor.reverse, cursor.position
    query_ordering = _reverse_ordering(ordering) if reverse else ordering
    queryset = queryset.order_by(*query_ordering)
    if current_position is not None:
        first = ordering[0]
        lookup = "lt" if cursor is not None and cursor.reverse != first.startswith("-") else "gt"
        queryset = queryset.filter(**{f"{first.removeprefix('-')}__{lookup}": current_position})
    results = list(queryset[offset : offset + PAGE_SIZE + 1])
    records = results[:PAGE_SIZE]
    following_position = _position(results[-1], ordering) if len(results) > len(records) else None
    if reverse:
        records.reverse()
        page = Page(
            base_url=str(request.url),
            cursor=cursor,
            ordering=ordering,
            records=records,
            has_next=current_position is not None or offset > 0,
            has_previous=following_position is not None,
        )
        if page.has_next:
            page.next_position = current_position
        if page.has_previous:
            page.previous_position = following_position
        return page
    page = Page(
        base_url=str(request.url),
        cursor=cursor,
        ordering=ordering,
        records=records,
        has_next=following_position is not None,
        has_previous=current_position is not None or offset > 0,
    )
    if page.has_next:
        page.next_position = following_position
    if page.has_previous:
        page.previous_position = current_position
    return page


def _next_link(page: Page) -> str | None:
    if not page.has_next:
        return None
    if page.records and page.cursor and page.cursor.reverse and page.cursor.offset:
        compare = _position(page.records[-1], page.ordering)
    else:
        compare = page.next_position
    offset = 0
    unique = False
    position: str | None = None
    for count, record in enumerate(reversed(page.records), start=1):
        position = _position(record, page.ordering)
        if position != compare:
            unique = True
            offset = count - 1
            break
        compare = position
        offset = count
    if page.records and not unique:
        if not page.has_previous:
            offset = PAGE_SIZE
            position = None
        elif page.cursor and page.cursor.reverse:
            offset = 0
            position = page.previous_position
        else:
            offset = (page.cursor.offset if page.cursor else 0) + PAGE_SIZE
            position = page.previous_position
    if not page.records:
        position = page.next_position
    return _encode_cursor(page, Cursor(offset=offset, reverse=False, position=position))


def _previous_link(page: Page) -> str | None:
    if not page.has_previous:
        return None
    if page.records and page.cursor and not page.cursor.reverse and page.cursor.offset:
        compare = _position(page.records[0], page.ordering)
    else:
        compare = page.previous_position
    offset = 0
    unique = False
    position: str | None = None
    for count, record in enumerate(page.records, start=1):
        position = _position(record, page.ordering)
        if position != compare:
            unique = True
            offset = count - 1
            break
        compare = position
        offset = count
    if page.records and not unique:
        if not page.has_next:
            offset = PAGE_SIZE
            position = None
        elif page.cursor and page.cursor.reverse:
            offset = page.cursor.offset + PAGE_SIZE
            position = page.next_position
        else:
            offset = 0
            position = page.next_position
    if not page.records:
        position = page.previous_position
    return _encode_cursor(page, Cursor(offset=offset, reverse=True, position=position))


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Datetime has wrong type")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TOKYO)
    return parsed


def _required(payload: dict[str, Any], name: str) -> Any:
    if name not in payload:
        raise ValueError(f"{name} is required")
    return payload[name]


def _apply_payload(record: Record, payload: dict[str, Any], *, partial: bool) -> None:
    if not partial:
        for field in ("label", "category", "amount", "posted_at"):
            _required(payload, field)
    if "label" in payload:
        record.label = str(payload["label"]).strip()
    if "category" in payload:
        record.category = str(payload["category"]).strip()
    if "amount" in payload:
        record.amount = Decimal(str(payload["amount"]))
    if "posted_at" in payload:
        record.posted_at = _parse_datetime(payload["posted_at"])


@app.get("/api/records/")
def list_records(request: Request) -> Response:
    try:
        page = _paginate(_filtered(request), request)
    except ValueError:
        return JSONResponse({"detail": "Invalid cursor"}, status_code=404)
    return JSONResponse(
        {
            "next": _next_link(page),
            "previous": _previous_link(page),
            "results": [_serialize(record) for record in page.records],
        }
    )


@app.post("/api/records/")
def create_record(payload: dict[str, Any] = REQUEST_BODY) -> Response:
    try:
        record = Record()
        _apply_payload(record, payload, partial=False)
        record.save()
    except (ArithmeticError, TypeError, ValueError):
        return JSONResponse({"detail": "Invalid input."}, status_code=400)
    return JSONResponse(_serialize(record), status_code=201)


@app.get("/api/records/{record_id}/")
def retrieve_record(record_id: int, request: Request) -> Response:
    record = Record.objects.filter(pk=record_id).first()
    if record is None:
        return JSONResponse({"detail": "No Record matches the given query."}, status_code=404)
    return _detail_response(request, _serialize(record))


def _update_record(
    record_id: int, request: Request, payload: dict[str, Any], partial: bool
) -> Response:
    record = Record.objects.filter(pk=record_id).first()
    if record is None:
        return JSONResponse({"detail": "No Record matches the given query."}, status_code=404)
    try:
        _apply_payload(record, payload, partial=partial)
        record.save()
    except (ArithmeticError, TypeError, ValueError):
        return JSONResponse({"detail": "Invalid input."}, status_code=400)
    return _detail_response(request, _serialize(record))


@app.put("/api/records/{record_id}/")
def update_record(
    record_id: int,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
) -> Response:
    return _update_record(record_id, request, payload, partial=False)


@app.patch("/api/records/{record_id}/")
def patch_record(
    record_id: int,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
) -> Response:
    return _update_record(record_id, request, payload, partial=True)


@app.delete("/api/records/{record_id}/", status_code=204)
def delete_record(record_id: int) -> Response:
    deleted, _ = Record.objects.filter(pk=record_id).delete()
    if not deleted:
        return JSONResponse({"detail": "No Record matches the given query."}, status_code=404)
    return Response(status_code=204)
