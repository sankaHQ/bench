from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from posts.models import Post


class PostApiTests(TestCase):
    def setUp(self) -> None:
        self.alice = User.objects.create(username="alice")
        self.bob = User.objects.create(username="bob")
        self.alice_token = Token.objects.create(user=self.alice, key="a" * 40)
        self.post = Post.objects.create(author=self.alice, title="Alpha post", body="hello")
        self.other = Post.objects.create(author=self.bob, title="Beta post", body="world")
        self.client = APIClient()

    def _authenticate(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.alice_token.key}")

    def test_list_requires_authentication(self) -> None:
        response = self.client.get("/api/posts/")
        self.assertEqual(response.status_code, 401)

    def test_authenticated_create_sets_author(self) -> None:
        self._authenticate()
        response = self.client.post(
            "/api/posts/",
            {"title": "New", "body": "text"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["author"], self.alice.id)
        self.assertEqual(Post.objects.count(), 3)

    def test_cannot_modify_another_authors_post(self) -> None:
        self._authenticate()
        response = self.client.patch(
            f"/api/posts/{self.other.id}/",
            {"title": "hax"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.title, "Beta post")
