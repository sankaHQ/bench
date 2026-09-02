from django.urls import include, path
from ledger.views import AccountViewSet, AuditLogViewSet, LedgerEntryViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")
router.register("entries", LedgerEntryViewSet, basename="ledgerentry")
router.register("audit", AuditLogViewSet, basename="auditlog")

urlpatterns = [path("api/", include(router.urls))]
