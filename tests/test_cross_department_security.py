import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

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
    # ---------------------------------------------------------
    # 1. Create two separate departments
    # ---------------------------------------------------------
    department_a = Department.objects.create(name="IT")
    department_b = Department.objects.create(name="HR")

    # ---------------------------------------------------------
    # 2. Create one user in each department
    # ---------------------------------------------------------
    user_a = User.objects.create_user(
        username="security_user_a",
        password="StrongPassword123!",
        role="Member",
        department=department_a,
    )

    user_b = User.objects.create_user(
        username="security_user_b",
        password="StrongPassword123!",
        role="Member",
        department=department_b,
    )

    # ---------------------------------------------------------
    # 3. Create one document for each department
    # ---------------------------------------------------------
    document_a = Document.objects.create(
        title="Department A Secret",
        file_type="text/plain",
        uploaded_by=user_a,
        department=department_a,
    )

    document_b = Document.objects.create(
        title="Department B Secret",
        file_type="text/plain",
        uploaded_by=user_b,
        department=department_b,
    )

    # ---------------------------------------------------------
    # 4. Login as User A
    # ---------------------------------------------------------
    client_a = APIClient()

    token_a = login_and_get_access_token(
        client_a,
        "security_user_a",
        "StrongPassword123!",
    )

    client_a.credentials(
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )

    # User A tries to access User B's document
    response_a = client_a.get(
        f"/api/documents/{document_b.id}/"
    )

    # Must be blocked
    assert response_a.status_code == 403

    # Make sure B's document data was not leaked
    assert "Department B Secret" not in str(response_a.data)

    # ---------------------------------------------------------
    # 5. Login as User B
    # ---------------------------------------------------------
    client_b = APIClient()

    token_b = login_and_get_access_token(
        client_b,
        "security_user_b",
        "StrongPassword123!",
    )

    client_b.credentials(
        HTTP_AUTHORIZATION=f"Bearer {token_b}"
    )

    # User B tries to access User A's document
    response_b = client_b.get(
        f"/api/documents/{document_a.id}/"
    )

    # Must be blocked
    assert response_b.status_code == 403

    # Make sure A's document data was not leaked
    assert "Department A Secret" not in str(response_b.data)