from __future__ import annotations

from typing import Any

from rest_framework import serializers

from orders.models import Order
from orders.state_machine import LEGAL_TRANSITIONS


class OrderSerializer(serializers.ModelSerializer):
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "status",
            "version",
            "total",
            "notes",
            "allowed_transitions",
        ]
        read_only_fields = ["id", "status", "version", "allowed_transitions"]

    def get_allowed_transitions(self, instance: Order) -> list[str]:
        return list(LEGAL_TRANSITIONS[instance.status])


class OrderPatchSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    notes = serializers.CharField(allow_blank=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if set(attrs) == {"version"}:
            raise serializers.ValidationError(
                {"non_field_errors": ["At least one mutable field is required."]}
            )
        return attrs


class TransitionSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=Order.Status.choices)
    version = serializers.IntegerField(min_value=1)
