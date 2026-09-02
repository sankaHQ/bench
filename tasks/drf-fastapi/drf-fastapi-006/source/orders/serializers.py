from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from rest_framework import serializers

from orders.models import Adjustment, Order, OrderItem


class AdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Adjustment
        fields = ["id", "code", "amount", "note"]
        read_only_fields = ["id"]

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            errors = {
                field: ["This field is required."]
                for field in ("code", "amount")
                if field not in data
            }
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class OrderItemSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1)
    adjustments = AdjustmentSerializer(many=True)

    class Meta:
        model = OrderItem
        fields = ["id", "sku", "quantity", "description", "adjustments"]
        read_only_fields = ["id"]

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            errors = {
                field: ["This field is required."]
                for field in ("sku", "quantity", "adjustments")
                if field not in data
            }
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = ["id", "reference", "customer_note", "items"]
        read_only_fields = ["id"]

    def create(self, validated_data: dict[str, Any]) -> Order:
        items_data = validated_data.pop("items")
        with transaction.atomic():
            order = Order.objects.create(**validated_data)
            self._create_items(order, items_data)
        return order

    def update(self, instance: Order, validated_data: dict[str, Any]) -> Order:
        items_data = validated_data.pop("items", serializers.empty)
        with transaction.atomic():
            for name, value in validated_data.items():
                setattr(instance, name, value)
            instance.save()
            if items_data is not serializers.empty:
                instance.items.all().delete()
                self._create_items(instance, items_data)
        return instance

    def _create_items(self, order: Order, items_data: list[dict[str, Any]]) -> None:
        for item_index, item_data in enumerate(items_data):
            adjustments_data = item_data.pop("adjustments")
            try:
                item = OrderItem.objects.create(order=order, **item_data)
            except IntegrityError as exc:
                errors = {
                    str(item_index): {
                        "non_field_errors": ["The fields order, sku must make a unique set."]
                    }
                }
                raise serializers.ValidationError({"items": errors}) from exc
            for adjustment_index, adjustment_data in enumerate(adjustments_data):
                try:
                    Adjustment.objects.create(item=item, **adjustment_data)
                except IntegrityError as exc:
                    errors = {
                        str(item_index): {
                            "adjustments": {
                                str(adjustment_index): {
                                    "non_field_errors": [
                                        "The fields item, code must make a unique set."
                                    ]
                                }
                            }
                        }
                    }
                    raise serializers.ValidationError({"items": errors}) from exc
