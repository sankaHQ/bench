from rest_framework import serializers

from widgets.models import Widget


class WidgetSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=0)

    class Meta:
        model = Widget
        fields = ["id", "name", "quantity"]
        read_only_fields = ["id"]
