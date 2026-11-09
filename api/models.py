
import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    action = models.CharField(
        max_length=50,
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "-timestamp"],
                name="audit_user_time_idx",
            ),
        ]
        ordering = ["-timestamp", "-id"]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"


class RateLimitConfig(models.Model):
    member_chat_requests_per_hour = models.PositiveIntegerField(
        default=50,
        help_text="Maximum chat requests per hour for Members.",
    )
    admin_chat_requests_per_hour = models.PositiveIntegerField(
        default=200,
        help_text="Maximum chat requests per hour for Admins.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Rate Limit Configuration"
        verbose_name_plural = "Rate Limit Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Chat API Rate Limits"


class ChatAnswer(models.Model):
    """
    One generated answer, stored so it can be rated and reused later.

    Feedback alone (a boolean next to an opaque ID) is not enough to
    improve the system: fine-tuning needs the question and the answer
    text, and reranking experiments need the citations that were shown.
    This table is the durable record that makes both possible.

    The primary key is a UUID generated *before* the row is written, so a
    streaming response can tell the client its `answer_id` on the first
    event and write the row once at the end.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="chat_answers",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_answers",
    )

    # Client-generated chat session identifier. It is intentionally not a
    # foreign key: conversations are a client-side concept and may span
    # many answers without needing their own table.
    conversation_id = models.CharField(max_length=255, blank=True)

    question = models.TextField()
    answer = models.TextField(blank=True, default="")
    citations = models.JSONField(default=list, blank=True)

    # False when the stream was aborted or failed midway, which keeps
    # half-written answers out of any future training set.
    is_complete = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["tenant", "-created_at"],
                name="chatanswer_tenant_time_idx",
            ),
            models.Index(
                fields=["tenant", "conversation_id"],
                name="chatanswer_tenant_conv_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.conversation_id} - {self.id}"


class AnswerFeedback(models.Model):
    """
    A single user's verdict on a single answer.

    The unique constraint is the real guarantee behind "one feedback per
    user per answer". A view-level existence check is a friendlier fast
    path, but two concurrent requests would both pass it; only the
    database constraint makes the rule airtight.
    """

    answer = models.ForeignKey(
        ChatAnswer,
        on_delete=models.CASCADE,
        related_name="feedback",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="answer_feedback",
    )

    # Denormalised tenant: analytics and future exports can filter by
    # organisation without joining through ChatAnswer.
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="answer_feedback",
    )

    is_positive = models.BooleanField()

    user_comment = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["answer", "user"],
                name="unique_feedback_per_user_answer",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "-created_at"],
                name="feedback_tenant_time_idx",
            ),
            models.Index(
                fields=["tenant", "is_positive"],
                name="feedback_tenant_sentiment_idx",
            ),
        ]

    def __str__(self):
        verdict = "positive" if self.is_positive else "negative"
        return f"{self.user} - {verdict} - {self.answer_id}"
