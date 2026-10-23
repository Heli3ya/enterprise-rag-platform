
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from tenants.models import Tenant
from departments.models import Department
from documents.models import Document


User = get_user_model()


def login_and_get_access_token(client, username, password):
    response = client.post(
        "/api/auth/login/",
        {
            "username": username,
            "password": password,
        },
        format="json",
    )

    assert response.status_code == 200
    assert "access" in response.data

    return response.data["access"]


@pytest.mark.django_db
def test_users_cannot_access_documents_from_another_department():
    tenant = Tenant.objects.create(
        name="Cross Department Test Organization"
    )

    department_a = Department.objects.create(
        name="IT",
        tenant=tenant,
    )
    department_b = Department.objects.create(
        name="HR",
        tenant=tenant,
    )

    user_a = User.objects.create_user(
        username="security_user_a",
        password="StrongPassword123!",
        role="Member",
        department=department_a,
        tenant=tenant,
    )

    user_b = User.objects.create_user(
        username="security_user_b",
        password="StrongPassword123!",
        role="Member",
        department=department_b,
        tenant=tenant,
    )

    document_a = Document.objects.create(
        title="Department A Secret",
        file_type="text/plain",
        uploaded_by=user_a,
        department=department_a,
        tenant=tenant,
    )

    document_b = Document.objects.create(
        title="Department B Secret",
        file_type="text/plain",
        uploaded_by=user_b,
        department=department_b,
        tenant=tenant,
    )

    client_a = APIClient()
    token_a = login_and_get_access_token(
        client_a,
        "security_user_a",
        "StrongPassword123!",
    )
    client_a.credentials(
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )

    response_a = client_a.get(
        f"/api/documents/{document_b.id}/"
    )

    assert response_a.status_code == 403
    assert "Department B Secret" not in str(response_a.data)

    client_b = APIClient()
    token_b = login_and_get_access_token(
        client_b,
        "security_user_b",
        "StrongPassword123!",
    )
    client_b.credentials(
        HTTP_AUTHORIZATION=f"Bearer {token_b}"
    )

    response_b = client_b.get(
        f"/api/documents/{document_a.id}/"
    )

    assert response_b.status_code == 403
    assert "Department A Secret" not in str(response_b.data)


@pytest.mark.django_db
def test_users_cannot_access_documents_from_another_tenant():
    tenant_a = Tenant.objects.create(
        name="Tenant A Security Test"
    )
    tenant_b = Tenant.objects.create(
        name="Tenant B Security Test"
    )

    department_a = Department.objects.create(
        name="Tenant A IT",
        tenant=tenant_a,
    )
    department_b = Department.objects.create(
        name="Tenant B IT",
        tenant=tenant_b,
    )

    user_a = User.objects.create_user(
        username="tenant_security_user_a",
        password="StrongPassword123!",
        role="Member",
        department=department_a,
        tenant=tenant_a,
    )
    user_b = User.objects.create_user(
        username="tenant_security_user_b",
        password="StrongPassword123!",
        role="Member",
        department=department_b,
        tenant=tenant_b,
    )

    document_b = Document.objects.create(
        title="Tenant B Confidential Document",
        file_type="text/plain",
        uploaded_by=user_b,
        department=department_b,
        tenant=tenant_b,
    )

    client_a = APIClient()
    token_a = login_and_get_access_token(
        client_a,
        "tenant_security_user_a",
        "StrongPassword123!",
    )
    client_a.credentials(
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )

    response = client_a.get(
        f"/api/documents/{document_b.id}/"
    )

    assert response.status_code in (403, 404)
    assert (
        "Tenant B Confidential Document"
        not in str(response.data)
    )
@pytest.mark.django_db
def test_department_list_only_returns_departments_from_users_tenant():
    tenant_a = Tenant.objects.create(name="Department List Tenant A")
    tenant_b = Tenant.objects.create(name="Department List Tenant B")

    department_a = Department.objects.create(
        name="Tenant A IT",
        tenant=tenant_a,
    )
    Department.objects.create(
        name="Tenant B HR",
        tenant=tenant_b,
    )

    user_a = User.objects.create_user(
        username="department_list_user_a",
        password="StrongPassword123!",
        role="Member",
        department=department_a,
        tenant=tenant_a,
    )

    client = APIClient()
    client.force_authenticate(user=user_a)

    response = client.get("/api/departments/")

    assert response.status_code == 200

    department_names = {
        item["name"] for item in response.data
    }

    assert "Tenant A IT" in department_names
    assert "Tenant B HR" not in department_names
