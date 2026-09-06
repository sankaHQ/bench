from rest_framework import serializers


class PatchSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, max_length=64)
    body = serializers.CharField(
        required=False, max_length=1024, allow_blank=True, trim_whitespace=False
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide title or body.")
        return attrs
