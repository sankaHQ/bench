import json

from django.test import TestCase

from documents.models import Document, RevisionEvent


class ConditionalWriteTests(TestCase):
    def test_strong_write_precondition_and_audit(self):
        Document.objects.create(id=1, owner="alpha", title="Guide", body="Initial.")
        options = {"content_type": "application/json", "HTTP_AUTHORIZATION": "ApiKey team-a"}
        response = self.client.patch(
            "/api/documents/1/",
            data=json.dumps({"title": "Changed"}),
            HTTP_IF_MATCH='W/"doc-1-r1"',
            **options,
        )
        self.assertEqual(response.status_code, 412)
        self.assertEqual(RevisionEvent.objects.count(), 0)
        response = self.client.patch(
            "/api/documents/1/",
            data=json.dumps({"title": "Changed"}),
            HTTP_IF_MATCH='"doc-1-r1"',
            **options,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["ETag"], '"doc-1-r2"')
        self.assertEqual(RevisionEvent.objects.count(), 1)
        response = self.client.get(
            "/api/documents/1/",
            HTTP_AUTHORIZATION="ApiKey team-a",
            HTTP_IF_NONE_MATCH='W/"doc-1-r2"',
        )
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")
