from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from documents.models import AccessToken, Document


class DocumentApiTests(TestCase):
    def setUp(self) -> None:
        self.alice = User.objects.create_user(username="alice")
        self.bob = User.objects.create_user(username="bob")
        self.admin = User.objects.create_user(username="admin", is_staff=True)
        self.alice_token = AccessToken.objects.create(
            key="a" * 40,
            user=self.alice,
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.document = Document.objects.create(
            owner=self.alice,
            title="Alpha document",
            body="private",
        )
        self.other = Document.objects.create(owner=self.bob, title="Beta document")
        self.client = APIClient()

    def _token(self, key: str | None = None) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {key or self.alice_token.key}")

    def test_list_is_open_but_bad_credentials_are_still_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/documents/").status_code, 200)
        self._token("x" * 40)
        response = self.client.get("/api/documents/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Token")

    def test_create_requires_authentication_and_injects_owner(self) -> None:
        self._token()
        response = self.client.post(
            "/api/documents/",
            {"title": "Created", "owner": self.bob.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["owner"], self.alice.id)

    def test_owner_permission_runs_on_detail_update(self) -> None:
        self._token()
        response = self.client.patch(
            f"/api/documents/{self.other.id}/",
            {"title": "hijacked"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.title, "Beta document")

    def test_destroy_and_review_are_staff_only(self) -> None:
        self._token()
        self.assertEqual(
            self.client.delete(f"/api/documents/{self.document.id}/").status_code,
            403,
        )
        self.assertEqual(
            self.client.post(f"/api/documents/{self.document.id}/review/").status_code,
            403,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.post(f"/api/documents/{self.document.id}/review/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reviewed"])
