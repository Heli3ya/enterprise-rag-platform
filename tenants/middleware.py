
class TenantMiddleware:
    """
    Attach the authenticated user's active tenant to the request
    when Django authentication has already identified the user.
    JWT-authenticated API requests are handled by TenantJWTAuthentication.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None

        user = getattr(request, "user", None)

        if user is not None and user.is_authenticated:
            tenant = getattr(user, "tenant", None)

            if tenant is not None and tenant.is_active:
                request.tenant = tenant

        return self.get_response(request)
