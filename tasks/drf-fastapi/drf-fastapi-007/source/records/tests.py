from django.test import TestCase
from rest_framework.test import APIClient

from records.models import Record


class ResponsePrecisionApiTests(TestCase):
    def setUp(self) -> None:
        rows = [
            (1, "Alpha opening", "retail", "10.00", "2026-01-01T00:00:00Z"),
            (2, "Beta opening", "retail", "10.00", "2026-01-01T00:00:00Z"),
            (3, "Operations fee", "ops", "2.50", "2026-01-01T01:00:00Z"),
            (4, "Alpha renewal", "sales", "100.10", "2026-01-01T02:00:00Z"),
            (5, "Closing balance", "ops", "0.00", "2026-01-01T03:00:00Z"),
        ]
        for pk, label, category, amount, posted_at in rows:
            Record.objects.create(
                id=pk,
                label=label,
                category=category,
                amount=amount,
                posted_at=posted_at,
            )
        self.client = APIClient()

    def test_cursor_walk_is_stable_across_newer_insert(self) -> None:
        first = self.client.get("/api/records/").json()
        self.assertEqual([row["id"] for row in first["results"]], [5, 4])
        Record.objects.create(
            label="Newest",
            category="ops",
            amount="1.00",
            posted_at="2026-01-01T04:00:00Z",
        )
        second = self.client.get(first["next"]).json()
        self.assertEqual([row["id"] for row in second["results"]], [3, 2])

    def test_search_and_ordering_compose_with_deterministic_ties(self) -> None:
        response = self.client.get("/api/records/?search=retail&ordering=amount")
        self.assertEqual([row["id"] for row in response.json()["results"]], [1, 2])

    def test_decimal_and_datetime_render_precisely(self) -> None:
        payload = self.client.get("/api/records/1/").json()
        self.assertEqual(payload["amount"], "10.00")
        self.assertEqual(payload["posted_at"], "2026-01-01T09:00:00+09:00")

    def test_matching_etag_returns_empty_304(self) -> None:
        first = self.client.get("/api/records/1/")
        response = self.client.get(
            "/api/records/1/",
            headers={"If-None-Match": first["ETag"]},
        )
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["ETag"], first["ETag"])
        self.assertEqual(response["Cache-Control"], "private, max-age=0")
        self.assertEqual(response["Vary"], "Accept")
