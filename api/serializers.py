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


class NegativeFeedbackSerializer(serializers.ModelSerializer):
    """
    One row of the admin "what went wrong" grid.

    The question and answer text are included on purpose: a thumbs-down
    with no context is not actionable, and the admin is the one person
    allowed to read another user's question in full. `citation_count`
    lets them tell "the model had no source" apart from "the model
    ignored the source it had".
    """

    answer_id = serializers.UUIDField(read_only=True)
    question = serializers.CharField(
        source="answer.question",
        read_only=True,
    )
    answer_text = serializers.CharField(
        source="answer.answer",
        read_only=True,
    )
    username = serializers.CharField(source="user.username", read_only=True)
    department_id = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    citation_count = serializers.SerializerMethodField()

    class Meta:
        model = AnswerFeedback
        fields = [
            "id",
            "answer_id",
            "question",
            "answer_text",
            "user_comment",
            "username",
            "department_id",
            "department_name",
            "citation_count",
            "created_at",
        ]
        read_only_fields = fields

    def get_department_id(self, obj):
        department = obj.answer.user.department

        return department.id if department else None

    def get_department_name(self, obj):
        department = obj.answer.user.department

        return department.name if department else None

    def get_citation_count(self, obj):
        citations = obj.answer.citations

        return len(citations) if isinstance(citations, list) else 0


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