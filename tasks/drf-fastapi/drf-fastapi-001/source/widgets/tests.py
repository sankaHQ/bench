from django.test import TestCase
from rest_framework.test import APIClient

from widgets.models import Widget


class WidgetApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.widget = Widget.objects.create(name="Alpha", quantity=3)

    def test_list(self) -> None:
        response = self.client.get("/api/widgets/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": self.widget.id, "name": "Alpha", "quantity": 3}])

    def test_create(self) -> None:
        response = self.client.post(
            "/api/widgets/",
            {"name": "Beta", "quantity": 7},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Widget.objects.count(), 2)

    def test_rejects_negative_quantity(self) -> None:
        response = self.client.post(
            "/api/widgets/",
            {"name": "Beta", "quantity": -1},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Widget.objects.count(), 1)
