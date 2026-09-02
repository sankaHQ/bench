from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from rest_framework.test import APIClient

from sales.models import Account, Transaction


class AggregateAndComputedFieldTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.alpha = Account.objects.create(
            code="ACCT-A",
            name="Alpha",
            region=Account.Region.NORTH,
        )
        self.beta = Account.objects.create(
            code="ACCT-B",
            name="Beta",
            region=Account.Region.NORTH,
        )
        self.south = Account.objects.create(
            code="ACCT-S",
            name="South",
            region=Account.Region.SOUTH,
        )
        self.west = Account.objects.create(
            code="ACCT-W",
            name="West",
            region=Account.Region.WEST,
        )
        self.alpha_posted = Transaction.objects.create(
            account=self.alpha,
            reference="TX-A-POSTED",
            state=Transaction.State.POSTED,
            amount=Decimal("10.00"),
            note="First",
        )
        self.alpha_pending = Transaction.objects.create(
            account=self.alpha,
            reference="TX-A-PENDING",
            state=Transaction.State.PENDING,
            amount=Decimal("3.50"),
            note="Waiting",
        )
        Transaction.objects.create(
            account=self.beta,
            reference="TX-B-POSTED",
            state=Transaction.State.POSTED,
            amount=Decimal("10.00"),
            note="Tie",
        )
        Transaction.objects.create(
            account=self.south,
            reference="TX-S-REFUND",
            state=Transaction.State.POSTED,
            amount=Decimal("-2.25"),
            note="Refund",
        )

    def all_account_results(self, ordering: str = "-posted_total") -> list[dict]:
        path = f"/api/accounts/?ordering={ordering}"
        results: list[dict] = []
        while path:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            results.extend(payload["results"])
            path = payload["next"]
        return results

    def test_list_has_exact_aggregate_and_method_fields(self) -> None:
        response = self.client.get("/api/accounts/?ordering=-posted_total")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 4)
        self.assertEqual(payload["previous"], None)
        self.assertEqual(
            parse_qs(urlparse(payload["next"]).query),
            {"ordering": ["-posted_total"], "page": ["2"]},
        )
        self.assertEqual(
            payload["results"],
            [
                {
                    "code": "ACCT-A",
                    "name": "Alpha",
                    "region": "north",
                    "transaction_count": 2,
                    "pending_count": 1,
                    "posted_total": "10.00",
                    "activity_state": "pending",
                    "latest_reference": "TX-A-PENDING",
                },
                {
                    "code": "ACCT-B",
                    "name": "Beta",
                    "region": "north",
                    "transaction_count": 1,
                    "pending_count": 0,
                    "posted_total": "10.00",
                    "activity_state": "settled",
                    "latest_reference": "TX-B-POSTED",
                },
            ],
        )

    def test_page_walking_preserves_computed_values_and_tie_order(self) -> None:
        results = self.all_account_results()

        self.assertEqual(
            [item["code"] for item in results],
            ["ACCT-A", "ACCT-B", "ACCT-W", "ACCT-S"],
        )
        by_code = {item["code"]: item for item in results}
        self.assertEqual(by_code["ACCT-W"]["posted_total"], "0.00")
        self.assertEqual(by_code["ACCT-W"]["activity_state"], "empty")
        self.assertIsNone(by_code["ACCT-W"]["latest_reference"])
        self.assertEqual(by_code["ACCT-S"]["posted_total"], "-2.25")

    def test_create_mutation_recomputes_list_and_summary(self) -> None:
        create = self.client.post(
            "/api/transactions/",
            {
                "account": "ACCT-W",
                "reference": "TX-W-POSTED",
                "state": "posted",
                "amount": "4.20",
                "note": "New",
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201)

        by_code = {item["code"]: item for item in self.all_account_results()}
        self.assertEqual(by_code["ACCT-W"]["posted_total"], "4.20")
        self.assertEqual(by_code["ACCT-W"]["transaction_count"], 1)
        self.assertEqual(by_code["ACCT-W"]["activity_state"], "settled")

        summary = self.client.get("/api/summary/").json()
        west = next(group for group in summary["groups"] if group["region"] == "west")
        self.assertEqual(west["posted_total"], "4.20")
        self.assertEqual(summary["grand_total"], "21.95")

    def test_patch_and_delete_mutations_recompute_aggregates(self) -> None:
        patch = self.client.patch(
            f"/api/transactions/{self.alpha_pending.pk}/",
            {"state": "posted", "amount": "3.75"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200)
        by_code = {item["code"]: item for item in self.all_account_results()}
        self.assertEqual(by_code["ACCT-A"]["posted_total"], "13.75")
        self.assertEqual(by_code["ACCT-A"]["pending_count"], 0)
        self.assertEqual(by_code["ACCT-A"]["activity_state"], "settled")

        delete = self.client.delete(f"/api/transactions/{self.alpha_posted.pk}/")
        self.assertEqual(delete.status_code, 204)
        by_code = {item["code"]: item for item in self.all_account_results()}
        self.assertEqual(by_code["ACCT-A"]["posted_total"], "3.75")
        self.assertEqual(by_code["ACCT-A"]["transaction_count"], 1)

    def test_summary_has_group_totals_and_zero_value_group(self) -> None:
        response = self.client.get("/api/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "groups": [
                    {
                        "region": "north",
                        "account_count": 2,
                        "transaction_count": 3,
                        "posted_total": "20.00",
                    },
                    {
                        "region": "south",
                        "account_count": 1,
                        "transaction_count": 1,
                        "posted_total": "-2.25",
                    },
                    {
                        "region": "west",
                        "account_count": 1,
                        "transaction_count": 0,
                        "posted_total": "0.00",
                    },
                ],
                "grand_total": "17.75",
            },
        )

    def test_fully_empty_summary_is_deterministic(self) -> None:
        Transaction.objects.all().delete()
        Account.objects.all().delete()

        response = self.client.get("/api/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"groups": [], "grand_total": "0.00"})

    def test_invalid_computed_ordering_has_exact_error(self) -> None:
        response = self.client.get("/api/accounts/?ordering=unknown")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"ordering": ['Unsupported ordering field "unknown".']},
        )
