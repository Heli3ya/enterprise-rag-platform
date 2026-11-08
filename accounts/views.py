from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


class LoginView(APIView):
    """
    JWT login endpoint with actionable error messages.

    The default SimpleJWT view answers every failure with the same
    message, which makes it impossible to tell a wrong password from a
    deactivated account or an account without an organization.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        username = str(request.data.get("username") or "").strip()
        password = str(request.data.get("password") or "")

        if not username or not password:
            return Response(
                {"detail": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(
            request=request,
            username=username,
            password=password,
        )

        if user is None:
            inactive = (
                User.objects.filter(
                    username__iexact=username,
                    is_active=False,
                )
                .only("id")
                .first()
            )

            if inactive is not None:
                return Response(
                    {
                        "detail": (
                            "This account is deactivated. "
                            "Please contact an administrator."
                        )
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {
                    "detail": (
                        "This account is deactivated. "
                        "Please contact an administrator."
                    )
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        tenant = getattr(user, "tenant", None)

        if tenant is None:
            return Response(
                {
                    "detail": (
                        "Your account is not assigned to an organization. "
                        "Please contact an administrator."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not tenant.is_active:
            return Response(
                {
                    "detail": (
                        "Your organization is inactive or unavailable."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )
