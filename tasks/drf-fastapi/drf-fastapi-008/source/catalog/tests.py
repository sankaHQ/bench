from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Entry


class LegacyMixedStyleApiTests(TestCase):
    def setUp(self) -> None:
        Entry.objects.create(
            code="guide.v2+draft",
            title="Migration guide",
            body="Shared legacy record",
            state="draft",
        )
        Entry.objects.create(
            code="release@2026.08",
            title="Release notes",
            body="Published record",
            state="published",
        )
        self.client = APIClient()

    def test_all_three_styles_return_the_same_collection(self) -> None:
        paths = [
            "/api/function/entries/",
            "/api/class/entries",
            "/api/viewset/entries/",
        ]
        payloads = [self.client.get(path).json() for path in paths]
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(payloads[1], payloads[2])

    def test_non_slug_code_has_detail_parity_including_dynamic_route(self) -> None:
        paths = [
            "/api/function/entries/guide.v2+draft/",
            "/api/class/entries/guide.v2+draft",
            "/api/viewset/entries/guide.v2+draft/",
            "/api/dynamic/entries/guide.v2+draft/",
        ]
        payloads = [self.client.get(path).json() for path in paths]
        self.assertTrue(all(payload == payloads[0] for payload in payloads))

    def test_validation_errors_match_across_styles(self) -> None:
        paths = [
            "/api/function/entries/",
            "/api/class/entries",
            "/api/viewset/entries/",
        ]
        responses = [
            self.client.post(path, {"code": "", "title": ""}, format="json") for path in paths
        ]
        self.assertEqual([response.status_code for response in responses], [400, 400, 400])
        self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(responses[1].json(), responses[2].json())

    def test_each_style_preserves_its_trailing_slash_contract(self) -> None:
        expected = {
            "/api/function/entries": 200,
            "/api/function/entries/": 200,
            "/api/class/entries": 200,
            "/api/class/entries/": 307,
            "/api/viewset/entries": 307,
            "/api/viewset/entries/": 200,
            "/api/dynamic/entries/guide.v2+draft": 404,
            "/api/dynamic/entries/guide.v2+draft/": 200,
        }
        for path, status_code in expected.items():
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, status_code)
