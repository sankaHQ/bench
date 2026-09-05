from __future__ import annotations

from rest_framework import serializers

from sales.models import Account, Transaction


class AccountMetricSerializer(serializers.ModelSerializer):
    transaction_count = serializers.IntegerField(read_only=True)
    pending_count = serializers.IntegerField(read_only=True)
    posted_total = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )
    activity_state = serializers.SerializerMethodField()
    latest_reference = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "code",
            "name",
            "region",
            "transaction_count",
            "pending_count",
            "posted_total",
            "activity_state",
            "latest_reference",
        ]

    def get_activity_state(self, instance: Account) -> str:
        transactions = instance.computed_transactions
        if not transactions:
            return "empty"
        if any(item.state == Transaction.State.PENDING for item in transactions):
            return "pending"
        return "settled"

    def get_latest_reference(self, instance: Account) -> str | None:
        transactions = instance.computed_transactions
        return transactions[0].reference if transactions else None


class TransactionSerializer(serializers.ModelSerializer):
    account = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Account.objects.all(),
    )

    class Meta:
        model = Transaction
        fields = ["id", "account", "reference", "state", "amount", "note"]
        read_only_fields = ["id"]


class SummaryGroupSerializer(serializers.Serializer):
    region = serializers.ChoiceField(choices=Account.Region.choices)
    account_count = serializers.IntegerField()
    transaction_count = serializers.IntegerField()
    posted_total = serializers.DecimalField(max_digits=12, decimal_places=2)


class SummarySerializer(serializers.Serializer):
    groups = SummaryGroupSerializer(many=True)
    grand_total = serializers.DecimalField(max_digits=12, decimal_places=2)
