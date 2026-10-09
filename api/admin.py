from django.contrib import admin
from django.core.cache import cache

from .models import RateLimitConfig


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