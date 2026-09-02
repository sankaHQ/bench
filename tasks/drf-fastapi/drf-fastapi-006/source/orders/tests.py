from copy import deepcopy

from django.test import TestCase
from rest_framework.test import APIClient

from orders.models import Adjustment, Order, OrderItem


class DeepOrderApiTests(TestCase):
    def setUp(self) -> None:
        self.order = Order.objects.create(
            id=1,
            reference="ORD-100",
            customer_note="priority",
        )
        first = OrderItem.objects.create(
            id=1,
            order=self.order,
            sku="SKU-A",
            quantity=2,
            description="alpha",
        )
        second = OrderItem.objects.create(
            id=2,
            order=self.order,
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
        self.client = APIClient()

    def test_create_writes_all_three_levels(self) -> None:
        response = self.client.post(
            "/api/orders/",
            {
                "reference": "ORD-NEW",
                "customer_note": "created",
                "items": [
                    {
                        "sku": "SKU-C",
                        "quantity": 3,
                        "description": "gamma",
                        "adjustments": [
                            {"code": "TAX", "amount": "1.25", "note": "city"},
                            {"code": "CREDIT", "amount": "-2.00", "note": ""},
                        ],
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created = Order.objects.get(reference="ORD-NEW")
        self.assertEqual(created.items.count(), 1)
        self.assertEqual(created.items.get().adjustments.count(), 2)

    def test_patch_without_items_preserves_nested_graph_byte_for_byte(self) -> None:
        before = deepcopy(self.client.get("/api/orders/1/").json()["items"])
        response = self.client.patch(
            "/api/orders/1/",
            {"customer_note": "changed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], before)

    def test_full_update_replaces_nested_lists(self) -> None:
        response = self.client.put(
            "/api/orders/1/",
            {
                "reference": "ORD-100-R",
                "customer_note": "replaced",
                "items": [
                    {
                        "sku": "SKU-R",
                        "quantity": 5,
                        "description": "replacement",
                        "adjustments": [{"code": "FEE", "amount": "3.00", "note": ""}],
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["sku"] for item in response.json()["items"]], ["SKU-R"])
        self.assertFalse(OrderItem.objects.filter(sku="SKU-A").exists())
        self.assertEqual(Adjustment.objects.count(), 1)

    def test_duplicate_adjustment_rolls_back_every_write(self) -> None:
        before = self.client.get("/api/orders/1/").json()
        response = self.client.put(
            "/api/orders/1/",
            {
                "reference": "ORD-BROKEN",
                "customer_note": "must roll back",
                "items": [
                    {
                        "sku": "SKU-C",
                        "quantity": 3,
                        "description": "third",
                        "adjustments": [
                            {"code": "TAX", "amount": "1.00", "note": "first"},
                            {"code": "TAX", "amount": "2.00", "note": "duplicate"},
                        ],
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "items": {
                    "0": {
                        "adjustments": {
                            "1": {
                                "non_field_errors": [
                                    "The fields item, code must make a unique set."
                                ]
                            }
                        }
                    }
                }
            },
        )
        self.assertEqual(self.client.get("/api/orders/1/").json(), before)

    def test_deep_validation_error_retains_both_indexes(self) -> None:
        response = self.client.post(
            "/api/orders/",
            {
                "reference": "ORD-BAD",
                "items": [
                    {
                        "sku": "SKU-C",
                        "quantity": 1,
                        "adjustments": [],
                    },
                    {
                        "sku": "SKU-D",
                        "quantity": 2,
                        "adjustments": [
                            {"code": "OK", "amount": "1.00"},
                            {"code": "BAD", "amount": "not-a-number"},
                        ],
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"items": {"1": {"adjustments": {"1": {"amount": ["A valid number is required."]}}}}},
        )
