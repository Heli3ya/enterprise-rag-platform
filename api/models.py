from django.conf import settings
from django.db import models


class AuditLog(models.Model):
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
