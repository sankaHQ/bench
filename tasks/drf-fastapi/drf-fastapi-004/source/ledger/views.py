from django.db import transaction
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import (
    CreateModelMixin,
    DestroyModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from ledger.models import Account, AuditLog, LedgerEntry
from ledger.serializers import (
    AccountSerializer,
    AuditLogSerializer,
    LedgerEntrySerializer,
    TransferSerializer,
)


class AccountViewSet(ModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        source = self.get_object()
        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_pk = serializer.validated_data["target"]
        amount = serializer.validated_data["amount"]
        with transaction.atomic():
            locked = {
                account.pk: account
                for account in Account.objects.select_for_update()
                .filter(pk__in={source.pk, target_pk})
                .order_by("pk")
            }
            source_account = locked[source.pk]
            target_account = locked.get(target_pk)
            if target_account is None:
                raise ValidationError({"target": ["Target account not found."]})
            if source_account.balance < amount:
                raise ValidationError({"amount": ["Insufficient funds."]})
            LedgerEntry.objects.create(account=source_account, amount=-amount, memo="transfer-out")
            LedgerEntry.objects.create(account=target_account, amount=amount, memo="transfer-in")
            AuditLog.objects.create(action="transfer", account_id=source_account.pk, delta=amount)
        source_account.refresh_from_db()
        return Response(self.get_serializer(source_account).data)


class LedgerEntryViewSet(
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    DestroyModelMixin,
    GenericViewSet,
):
    queryset = LedgerEntry.objects.all()
    serializer_class = LedgerEntrySerializer


class AuditLogViewSet(ListModelMixin, GenericViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
