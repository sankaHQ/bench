from decimal import Decimal

from rest_framework import serializers

from ledger.models import Account, AuditLog, LedgerEntry


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "name", "balance"]
        read_only_fields = ["id", "balance"]


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["id", "account", "amount", "memo"]
        read_only_fields = ["id"]


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ["id", "action", "account_id", "delta"]
        read_only_fields = ["id", "action", "account_id", "delta"]


class TransferSerializer(serializers.Serializer):
    target = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
