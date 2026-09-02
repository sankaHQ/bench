from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from orders.models import Order, OrderEvent
from orders.state_machine import LEGAL_TRANSITIONS


class StateMachineAndConcurrencyTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.order = Order.objects.create(
            number="ORD-010",
            total=Decimal("125.00"),
            notes="Initial",
        )
        OrderEvent.objects.create(
            order=self.order,
            kind=OrderEvent.Kind.CREATED,
            from_status=self.order.status,
            to_status=self.order.status,
            version=1,
        )

    def transition(self, order: Order, target: str, version: int | None = None):
        return self.client.post(
            f"/api/orders/{order.pk}/transition/",
            {"to_status": target, "version": version or order.version},
            format="json",
        )

    def database_snapshot(self) -> tuple[list[dict], list[dict]]:
        orders = list(Order.objects.order_by("id").values())
        events = list(OrderEvent.objects.order_by("id").values())
        return orders, events

    def test_create_starts_at_version_one_with_one_event(self) -> None:
        response = self.client.post(
            "/api/orders/",
            {"number": "ORD-NEW", "total": "10.00", "notes": "Created"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["version"], 1)
        created = Order.objects.get(number="ORD-NEW")
        self.assertEqual(
            list(created.events.values_list("kind", "version")),
            [("created", 1)],
        )

    def test_patch_increments_version_and_event_exactly_once(self) -> None:
        response = self.client.patch(
            f"/api/orders/{self.order.pk}/",
            {"version": 1, "notes": "Edited", "total": "130.25"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 2)
        self.order.refresh_from_db()
        self.assertEqual(self.order.version, 2)
        self.assertEqual(self.order.total, Decimal("130.25"))
        self.assertEqual(
            list(self.order.events.values_list("kind", "version")),
            [("created", 1), ("updated", 2)],
        )

    def test_stale_patch_returns_exact_conflict_and_changes_no_table(self) -> None:
        before = self.database_snapshot()
        response = self.client.patch(
            f"/api/orders/{self.order.pk}/",
            {"version": 9, "notes": "Must not persist"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "detail": "Version conflict.",
                "expected_version": 1,
                "provided_version": 9,
            },
        )
        self.assertEqual(self.database_snapshot(), before)

    def test_happy_path_advances_one_version_per_transition(self) -> None:
        expected = [
            (Order.Status.SUBMITTED, 2),
            (Order.Status.APPROVED, 3),
            (Order.Status.SHIPPED, 4),
        ]
        for target, version in expected:
            response = self.transition(self.order, target)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["version"], version)
            self.order.refresh_from_db()

        self.assertEqual(
            list(self.order.events.values_list("to_status", "version")),
            [
                ("draft", 1),
                ("submitted", 2),
                ("approved", 3),
                ("shipped", 4),
            ],
        )

    def test_entire_known_transition_matrix_has_exact_outcomes(self) -> None:
        statuses = [choice for choice, _label in Order.Status.choices]
        case = 0
        for source in statuses:
            for target in statuses:
                case += 1
                order = Order.objects.create(
                    number=f"MATRIX-{case:02d}",
                    status=source,
                    version=1,
                    total=Decimal("1.00"),
                )
                response = self.transition(order, target)
                if target in LEGAL_TRANSITIONS[source]:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["version"], 2)
                else:
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(
                        response.json(),
                        {
                            "detail": (f"Transition from {source} to {target} is not allowed."),
                            "allowed": list(LEGAL_TRANSITIONS[source]),
                        },
                    )

    def test_unknown_transition_target_is_a_validation_error(self) -> None:
        response = self.client.post(
            f"/api/orders/{self.order.pk}/transition/",
            {"to_status": "returned", "version": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"to_status": ['"returned" is not a valid choice.']},
        )

    def test_stale_transition_changes_no_table(self) -> None:
        before = self.database_snapshot()
        response = self.transition(self.order, Order.Status.SUBMITTED, version=7)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "detail": "Version conflict.",
                "expected_version": 1,
                "provided_version": 7,
            },
        )
        self.assertEqual(self.database_snapshot(), before)
