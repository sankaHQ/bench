from __future__ import annotations

import hashlib
import tempfile
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from artifacts.models import Artifact


class FileAndContentNegotiationTests(TestCase):
    def setUp(self) -> None:
        self.media_directory = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.settings_override.enable()
        self.client = APIClient()

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.media_directory.cleanup()

    def upload(
        self,
        *,
        key: str = "guide",
        filename: str = "guide.txt",
        content: bytes = b"alpha\nbeta\n",
        content_type: str = "text/plain",
        path: str = "/api/files/",
    ) -> Any:
        return self.client.post(
            path,
            {
                "key": key,
                "label": "Migration guide",
                "file": SimpleUploadedFile(filename, content, content_type=content_type),
            },
            format="multipart",
        )

    def test_multipart_upload_persists_exact_bytes_and_metadata(self) -> None:
        content = b"alpha\r\nbeta\n"
        response = self.upload(content=content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "id": 1,
                "key": "guide",
                "label": "Migration guide",
                "original_name": "guide.txt",
                "content_type": "text/plain",
                "byte_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "download_path": "/api/files/1/download/",
            },
        )
        artifact = Artifact.objects.get(key="guide")
        with artifact.file.open("rb") as stored:
            self.assertEqual(stored.read(), content)

    def test_raw_multipart_boundary_is_parsed_on_api_suffix(self) -> None:
        boundary = b"SankaBoundary009"
        content = b"boundary-data\n"
        body = b"\r\n".join(
            [
                b"--" + boundary,
                b'Content-Disposition: form-data; name="key"',
                b"",
                b"boundary-file",
                b"--" + boundary,
                b'Content-Disposition: form-data; name="label"',
                b"",
                b"Boundary upload",
                b"--" + boundary,
                b'Content-Disposition: form-data; name="file"; filename="boundary.txt"',
                b"Content-Type: text/plain",
                b"",
                content,
                b"--" + boundary + b"--",
                b"",
            ]
        )

        response = self.client.generic(
            "POST",
            "/api/files.api",
            data=body,
            content_type="multipart/form-data; boundary=SankaBoundary009",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Content-Type"], "application/vnd.sanka.file+json")
        artifact = Artifact.objects.get(key="boundary-file")
        with artifact.file.open("rb") as stored:
            self.assertEqual(stored.read(), content)

    def test_wrong_extension_has_exact_error_and_does_not_persist(self) -> None:
        response = self.upload(filename="payload.exe")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"file": ["Only files with .csv, .json, or .txt extensions are allowed."]},
        )
        self.assertFalse(Artifact.objects.exists())

    def test_oversized_file_has_exact_error_and_does_not_persist(self) -> None:
        response = self.upload(content=b"x" * 33)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"file": ["File must be 32 bytes or smaller."]},
        )
        self.assertFalse(Artifact.objects.exists())

    def test_download_preserves_bytes_and_attachment_headers(self) -> None:
        content = b"one,two\r\n3,4\r\n"
        self.upload(filename="report.csv", content=content, content_type="text/csv")

        response = self.client.get("/api/files/1/download.json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), content)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(response["Content-Length"], str(len(content)))
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="report.csv"',
        )

    def test_json_and_api_suffixes_negotiate_exact_media_types(self) -> None:
        self.upload()

        canonical = self.client.get("/api/files/1/")
        json_suffix = self.client.get("/api/files/1.json")
        api_suffix = self.client.get("/api/files/1.api")
        unsupported = self.client.get("/api/files/1.xml")

        self.assertEqual(canonical.status_code, 200)
        self.assertEqual(json_suffix.status_code, 200)
        self.assertEqual(api_suffix.status_code, 200)
        self.assertEqual(unsupported.status_code, 404)
        self.assertEqual(canonical.json(), json_suffix.json())
        self.assertEqual(json_suffix.json(), api_suffix.json())
        self.assertEqual(json_suffix["Content-Type"], "application/json")
        self.assertEqual(api_suffix["Content-Type"], "application/vnd.sanka.file+json")
