from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from documents.auth import ApiKeyAuth
from documents.logic import headers, matches, mutate, representation
from documents.models import Document
from documents.serializers import PatchSerializer


class DocumentView(APIView):
    authentication_classes = [ApiKeyAuth]
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def get(self, request, identifier):
        document = Document.objects.filter(
            id=identifier, owner=request.user.username, deleted=False
        ).first()
        if document is None:
            return Response({"detail": "Document not found."}, status=404)
        if matches(request.headers.get("If-None-Match", ""), document, weak=True):
            return Response(status=304, headers=headers(document))
        return Response(representation(document), headers=headers(document))

    def patch(self, request, identifier):
        serializer = PatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body, status, response_headers = mutate(
            request.user.username,
            identifier,
            request.headers.get("If-Match", ""),
            serializer.validated_data,
        )
        return Response(body, status=status, headers=response_headers)

    def delete(self, request, identifier):
        body, status, response_headers = mutate(
            request.user.username,
            identifier,
            request.headers.get("If-Match", ""),
            {},
            delete=True,
        )
        return Response(body, status=status, headers=response_headers)
