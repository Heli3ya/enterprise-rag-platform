
from django.core.cache import cache
from rest_framework.throttling import SimpleRateThrottle

from .models import RateLimitConfig


CONFIG_CACHE_KEY = "rate_limit_config:chat"
CONFIG_CACHE_TIMEOUT = 60


class ChatUserRateThrottle(SimpleRateThrottle):
    scope = "chat"

    def allow_request(self, request, view):
        config = cache.get(CONFIG_CACHE_KEY)

        if config is None:
            config_obj = RateLimitConfig.objects.filter(pk=1).first()

            if config_obj is None:
                config_obj = RateLimitConfig.objects.create(pk=1)

            config = {
                "member": config_obj.member_chat_requests_per_hour,
                "admin": config_obj.admin_chat_requests_per_hour,
            }

            cache.set(
                CONFIG_CACHE_KEY,
                config,
                timeout=CONFIG_CACHE_TIMEOUT,
            )

        if (
            request.user.is_authenticated
            and getattr(request.user, "role", None) == "Admin"
        ):
            limit = config["admin"]
        else:
            limit = config["member"]

        self.rate = f"{limit}/hour"
        self.num_requests, self.duration = self.parse_rate(self.rate)

        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            ident = f"user-{request.user.pk}"
        else:
            ident = f"ip-{self.get_ident(request)}"

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
