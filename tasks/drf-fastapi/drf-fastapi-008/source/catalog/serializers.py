from rest_framework import serializers

from catalog.models import Entry


class EntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Entry
        fields = ["id", "code", "title", "body", "state"]
        read_only_fields = ["id"]
