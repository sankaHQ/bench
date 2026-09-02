from __future__ import annotations

from typing import Any

from catalog.views import (
    EntryViewSet,
    LegacyEntryCollectionAPIView,
    LegacyEntryDetailAPIView,
    function_entry_collection,
    function_entry_detail,
)
from django.http import HttpRequest, HttpResponse
from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("entries", EntryViewSet, basename="entry")


def permanent_style_redirect(
    request: HttpRequest,
    target: str,
    code: str | None = None,
) -> HttpResponse:
    if code is not None:
        target = target.format(code=code)
    return HttpResponse(
        status=307,
        headers={"Location": request.build_absolute_uri(target)},
    )


urlpatterns = [
    re_path(
        r"^api/function/entries$",
        function_entry_collection,
        name="function-entry-collection-no-slash",
    ),
    re_path(
        r"^api/function/entries/$",
        function_entry_collection,
        name="function-entry-collection",
    ),
    re_path(
        r"^api/function/entries/(?P<code>[^/]+)$",
        function_entry_detail,
        name="function-entry-detail-no-slash",
    ),
    re_path(
        r"^api/function/entries/(?P<code>[^/]+)/$",
        function_entry_detail,
        name="function-entry-detail",
    ),
    path(
        "api/class/entries",
        LegacyEntryCollectionAPIView.as_view(),
        name="class-entry-collection",
    ),
    path(
        "api/class/entries/",
        permanent_style_redirect,
        {"target": "/api/class/entries"},
        name="class-entry-collection-redirect",
    ),
    re_path(
        r"^api/class/entries/(?P<code>[^/]+)$",
        LegacyEntryDetailAPIView.as_view(),
        name="class-entry-detail",
    ),
    re_path(
        r"^api/class/entries/(?P<code>[^/]+)/$",
        permanent_style_redirect,
        {"target": "/api/class/entries/{code}"},
        name="class-entry-detail-redirect",
    ),
    path(
        "api/viewset/entries",
        permanent_style_redirect,
        {"target": "/api/viewset/entries/"},
        name="viewset-entry-collection-redirect",
    ),
    re_path(
        r"^api/viewset/entries/(?P<code>[^/]+)$",
        permanent_style_redirect,
        {"target": "/api/viewset/entries/{code}/"},
        name="viewset-entry-detail-redirect",
    ),
    path("api/viewset/", include(router.urls)),
]

# This mirrors the legacy route-table style used by large Django projects:
# regular expressions are formatted from shared pattern options and appended
# after the main URL list has been declared. The nested expression is valid
# Django routing syntax but cannot be reduced losslessly to one path template.
pattern_opts = {"legacy_code": r"(?:[-\w.+@]+)"}
dynamic_route_specs: list[tuple[str, Any, str]] = [
    (
        r"^api/dynamic/entries/(?P<code>{legacy_code})/$".format(**pattern_opts),
        function_entry_detail,
        "dynamic-entry-detail",
    )
]
dynamic_urls = [re_path(pattern, view, name=name) for pattern, view, name in dynamic_route_specs]
urlpatterns += dynamic_urls
