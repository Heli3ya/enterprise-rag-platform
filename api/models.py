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