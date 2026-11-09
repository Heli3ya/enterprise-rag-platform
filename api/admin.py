from django.contrib import admin
from django.core.cache import cache

from .models import AnswerFeedback, ChatAnswer, RateLimitConfig


CONFIG_CACHE_KEY = "rate_limit_config:chat"


@admin.register(RateLimitConfig)
class RateLimitConfigAdmin(admin.ModelAdmin):
    list_display = (
        "member_chat_requests_per_hour",
        "admin_chat_requests_per_hour",
        "updated_at",
    )

    def has_add_permission(self, request):
        return (
            super().has_add_permission(request)
            and not RateLimitConfig.objects.exists()
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete(CONFIG_CACHE_KEY)


@admin.register(ChatAnswer)
class ChatAnswerAdmin(admin.ModelAdmin):
    """Read-only view of stored answers, used to audit feedback data."""

    list_display = (
        "id",
        "user",
        "tenant",
        "conversation_id",
        "is_complete",
        "created_at",
    )
    list_filter = ("is_complete", "tenant", "created_at")
    search_fields = ("question", "answer", "conversation_id", "user__username")
    readonly_fields = (
        "id",
        "tenant",
        "user",
        "conversation_id",
        "question",
        "answer",
        "citations",
        "is_complete",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AnswerFeedback)
class AnswerFeedbackAdmin(admin.ModelAdmin):
    """Feedback inbox for review and export."""

    list_display = (
        "id",
        "answer",
        "user",
        "tenant",
        "is_positive",
        "created_at",
    )
    list_filter = ("is_positive", "tenant", "created_at")
    search_fields = (
        "user_comment",
        "user__username",
        "answer__question",
        "answer__answer",
    )
    readonly_fields = (
        "answer",
        "user",
        "tenant",
        "is_positive",
        "user_comment",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False