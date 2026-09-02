from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from catalog.models import Entry
from catalog.serializers import EntrySerializer


def _entry(code: str) -> Entry:
    return get_object_or_404(Entry, code=code)


def _save(
    instance: Entry | None,
    data: Any,
    *,
    partial: bool = False,
) -> Response:
    serializer = EntrySerializer(instance, data=data, partial=partial)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    response_status = status.HTTP_200_OK if instance else status.HTTP_201_CREATED
    return Response(serializer.data, status=response_status)


@api_view(["GET", "POST"])
def function_entry_collection(request: Request) -> Response:
    if request.method == "GET":
        return Response(EntrySerializer(Entry.objects.all(), many=True).data)
    return _save(None, request.data)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
def function_entry_detail(request: Request, code: str) -> Response:
    entry = _entry(code)
    if request.method == "GET":
        return Response(EntrySerializer(entry).data)
    if request.method == "DELETE":
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return _save(entry, request.data, partial=request.method == "PATCH")


class HandRolledDispatchAPIView(APIView):
    """APIView base that performs the dispatch lifecycle explicitly."""

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self.args = args
        self.kwargs = kwargs
        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        self.headers = self.default_response_headers

        try:
            self.initial(request, *args, **kwargs)
            method = request.method.lower()
            if method in self.http_method_names:
                handler = getattr(self, method, self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed
            response = handler(request, *args, **kwargs)
        except Exception as exc:
            response = self.handle_exception(exc)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response


class LegacyEntryCollectionAPIView(HandRolledDispatchAPIView):
    def get(self, request: Request) -> Response:
        return Response(EntrySerializer(Entry.objects.all(), many=True).data)

    def post(self, request: Request) -> Response:
        return _save(None, request.data)


class LegacyEntryDetailAPIView(HandRolledDispatchAPIView):
    def get(self, request: Request, code: str) -> Response:
        return Response(EntrySerializer(_entry(code)).data)

    def put(self, request: Request, code: str) -> Response:
        return _save(_entry(code), request.data)

    def patch(self, request: Request, code: str) -> Response:
        return _save(_entry(code), request.data, partial=True)

    def delete(self, request: Request, code: str) -> Response:
        _entry(code).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EntryViewSet(ModelViewSet):
    queryset = Entry.objects.all()
    serializer_class = EntrySerializer
    lookup_field = "code"
    lookup_value_regex = r"[^/]+"
