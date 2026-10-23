
import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from tenants.models import Tenant
from departments.models import Department
from documents.models import Document


User = get_user_model()


@pytest.mark.django_db
def test_expired_jwt_token_is_rejected():
    tenant = Tenant.objects.create(
        name="JWT Security Test Organization"
    )
    department = Department.objects.create(
        name="Security",
        tenant=tenant,
    )

    user = User.objects.create_user(
        username="jwt_security_user",
        password="StrongPassword123!",
        role="Member",
        department=department,
        tenant=tenant,
    )

    document = Document.objects.create(
        title="JWT Security Test Document",
        file_type="text/plain",
        uploaded_by=user,
        department=department,
        tenant=tenant,
    )

    token = AccessToken.for_user(user)
    token.set_exp(lifetime=timedelta(seconds=-1))

    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(token)}"
    )

    response = client.get(
        f"/api/documents/{document.id}/"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_invalid_jwt_token_is_rejected():
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION="Bearer this-is-an-invalid-token"
    )

    response = client.get("/api/documents/1/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_revoked_refresh_token_cannot_be_reused():
    tenant = Tenant.objects.create(
        name="JWT Revocation Test Organization"
    )
    department = Department.objects.create(
        name="Revocation Security",
        tenant=tenant,
    )

    user = User.objects.create_user(
        username="revoked_token_user",
        password="StrongPassword123!",
        role="Member",
        department=department,
        tenant=tenant,
    )

    refresh_token = RefreshToken.for_user(user)
    refresh_token.blacklist()

    client = APIClient()

    response = client.post(
        "/api/auth/refresh/",
        {
            "refresh": str(refresh_token),
        },
        format="json",
    )

    assert response.status_code == 401
