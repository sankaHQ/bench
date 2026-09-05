from datetime import UTC, datetime

from django.test import TestCase

from reservations.logic import book, cancel, local_time
from reservations.models import BookingEvent, Reservation, Resource


class ReservationContractTests(TestCase):
    def test_dst_requires_fold_and_rejects_nonexistent_time(self):
        self.assertEqual(
            local_time("2026-11-01T01:30", "America/New_York", None, "start")[1],
            {"fold": ["Required for an ambiguous local time."]},
        )
        self.assertEqual(
            local_time("2026-11-01T01:30", "America/New_York", 1, "start")[0],
            datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
        )
        self.assertEqual(
            local_time("2026-03-08T02:30", "America/New_York", None, "start")[1],
            {"start": ["Local time does not exist in this timezone."]},
        )

    def test_adjacent_capacity_and_idempotent_cancel(self):
        Resource.objects.create(id=1, owner="alpha", name="Room", capacity=2)
        data = {
            "resource": 1,
            "start": "2026-10-01T10:00",
            "end": "2026-10-01T11:00",
            "timezone": "UTC",
            "seats": 2,
        }
        self.assertEqual(book("alpha", data)[1], 201)
        self.assertEqual(book("alpha", data)[1], 409)
        self.assertEqual(
            book("alpha", {**data, "start": "2026-10-01T11:00", "end": "2026-10-01T12:00"})[1], 201
        )
        cancel("alpha", 1)
        cancel("alpha", 1)
        self.assertEqual(Reservation.objects.count(), 2)
        self.assertEqual(BookingEvent.objects.filter(action="cancelled").count(), 1)
