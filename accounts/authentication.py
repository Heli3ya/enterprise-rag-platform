from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class TenantJWTAuthentication(JWTAuthentication):
    """
    Authenticate the user and validate the user's tenant for API requests.
    """

    def authenticate(self, request):
        result = super().authenticate(request)

        if result is None:
            return None

        user, validated_token = result
        tenant = getattr(user, "tenant", None)

        if tenant is None:
            raise AuthenticationFailed(
                "Your account is not assigned to an organization."
            )

        if not tenant.is_active:
            raise AuthenticationFailed(
                "Your organization is inactive."
            )

        request.tenant = tenant

        return user, validated_token
