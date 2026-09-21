from rest_framework import serializers
from api.models import AuditLog

class SearchQuerySerializer(serializers.Serializer):
    query_text = serializers.CharField(
        max_length=1000,
        allow_blank=False,
        trim_whitespace=True,
    )

    top_k = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=5,
    )

class ChatAskSerializer(serializers.Serializer):
    question = serializers.CharField(
        max_length=1000,
        allow_blank=False,
        trim_whitespace=True,
    )

    conversation_id = serializers.CharField(
        max_length=255,
        allow_blank=False,
        trim_whitespace=True,
    )

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "user",
            "action",
            "timestamp",
        ]
        read_only_fields = [
            "id",
            "user",
            "action",
            "timestamp",
        ]