from rest_framework import serializers
from api.models import AnswerFeedback, AuditLog

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


class RagQuerySerializer(SearchQuerySerializer):
    """
    Search input plus the conversation handle.

    Kept separate from `SearchQuerySerializer` so the plain search
    endpoint does not advertise a field it ignores.
    """

    conversation_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
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


class FeedbackCreateSerializer(serializers.Serializer):
    """
    Input for POST /api/chat/feedback/.

    The comment is capped at 2000 characters: it ends up in training and
    analysis exports, and unbounded free text would let one client store
    megabytes per request.
    """

    answer_id = serializers.UUIDField()

    is_positive = serializers.BooleanField()

    user_comment = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )


class AnswerFeedbackSerializer(serializers.ModelSerializer):
    answer_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = AnswerFeedback
        fields = [
            "id",
            "answer_id",
            "is_positive",
            "user_comment",
            "created_at",
        ]
        read_only_fields = fields


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