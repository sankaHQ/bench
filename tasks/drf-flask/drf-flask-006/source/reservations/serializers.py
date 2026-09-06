from rest_framework import serializers


class BookingSerializer(serializers.Serializer):
    resource = serializers.IntegerField(min_value=1)
    start = serializers.CharField()
    end = serializers.CharField()
    timezone = serializers.CharField()
    fold = serializers.IntegerField(required=False, min_value=0, max_value=1)
    seats = serializers.IntegerField(min_value=1, max_value=20)
