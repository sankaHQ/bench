from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction

from reservations.models import BookingEvent, Reservation, Resource


def local_time(value, zone_name, fold, field):
    try:
        naive = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None, {field: ["Use an ISO local date and time."]}
    if naive.tzinfo is not None:
        return None, {field: ["Supply a local time without an offset."]}
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return None, {"timezone": ["Unknown timezone."]}
    candidates = [naive.replace(tzinfo=zone, fold=n).astimezone(UTC) for n in (0, 1)]
    valid = [candidate.astimezone(zone).replace(tzinfo=None) == naive for candidate in candidates]
    if not any(valid):
        return None, {field: ["Local time does not exist in this timezone."]}
    if candidates[0] != candidates[1] and fold is None:
        return None, {"fold": ["Required for an ambiguous local time."]}
    return candidates[fold or 0], None


def representation(reservation):
    return {
        "id": reservation.id,
        "resource": reservation.resource_id,
        "start": reservation.start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "end": reservation.end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "seats": reservation.seats,
        "cancelled": reservation.cancelled,
    }


def book(owner, data):
    start, error = local_time(data["start"], data["timezone"], data.get("fold"), "start")
    if error:
        return error, 400
    end, error = local_time(data["end"], data["timezone"], data.get("fold"), "end")
    if error:
        return error, 400
    if end <= start:
        return {"end": ["Must be after start in UTC."]}, 400
    with transaction.atomic():
        resource = (
            Resource.objects.select_for_update().filter(id=data["resource"], owner=owner).first()
        )
        if resource is None:
            return {"detail": "Resource not found."}, 404
        events = [(start, data["seats"]), (end, -data["seats"])]
        for previous in Reservation.objects.filter(
            resource=resource, cancelled=False, start__lt=end, end__gt=start
        ):
            events.extend(
                [
                    (max(start, previous.start), previous.seats),
                    (min(end, previous.end), -previous.seats),
                ]
            )
        used = 0
        # End events precede starts at equal timestamps: intervals are half-open.
        for _, delta in sorted(events):
            used += delta
            if used > resource.capacity:
                return {"detail": "Capacity exceeded."}, 409
        reservation = Reservation.objects.create(
            resource=resource, start=start, end=end, seats=data["seats"]
        )
        BookingEvent.objects.create(reservation=reservation, action="created")
        return representation(reservation), 201


def cancel(owner, identifier):
    with transaction.atomic():
        reservation = (
            Reservation.objects.select_for_update()
            .filter(id=identifier, resource__owner=owner)
            .first()
        )
        if reservation is None:
            return {"detail": "Reservation not found."}, 404
        if not reservation.cancelled:
            reservation.cancelled = True
            reservation.save(update_fields=["cancelled"])
            BookingEvent.objects.create(reservation=reservation, action="cancelled")
        return representation(reservation), 200
