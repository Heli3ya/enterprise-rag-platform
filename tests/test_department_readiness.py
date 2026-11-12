"""
Sub-task 3 (API half) — the dashboard needs one cheap call to decide
whether to show the cold-start empty state.

The important nuance: a department that only contains the auto-generated
guide is still "empty" for the user. `document_count` therefore counts
user documents, while `has_searchable_content` tells the UI whether the
assistant can answer anything at all (it can, from the guide).
"""

import pytest
from rest_framework.test import APIClient

from departments.models import Department
from documents.models import Document
from tests.factories import (
    AdminFactory,
    DocumentFactory,
    TenantFactory,
    UserFactory,
    create_department,
)


READINESS_URL = "/api/departments/readiness/"


def build_department_with_guide(name="Finance"):
    """A realistic new department: admin created it, guide exists."""

    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)
    department = create_department(tenant, name, creator=admin)
    member = UserFactory(tenant=tenant, department=department)

    return tenant, admin, department, member


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


@pytest.mark.django_db
def test_cold_start_department_is_empty_but_not_silent():
    _, _, department, member = build_department_with_guide()

    response = client_for(member).get(READINESS_URL)

    assert response.status_code == 200

    body = response.json()
    guide = Document.objects.get(department=department, is_system=True)

    assert body["department_id"] == department.id
    assert body["department_name"] == department.name
    # The guide does not make the department look populated...
    assert body["document_count"] == 0
    assert body["is_empty"] is True
    # ...but it does make it answerable.
    assert body["has_searchable_content"] is True
    assert body["onboarding_document_id"] == guide.id


@pytest.mark.django_db
def test_uploading_a_document_clears_the_empty_state():
    tenant, _, department, member = build_department_with_guide()

    DocumentFactory(
        department=department,
        tenant=tenant,
        uploaded_by=member,
        title="Budget 2026",
    )

    body = client_for(member).get(READINESS_URL).json()

    assert body["document_count"] == 1
    assert body["is_empty"] is False


@pytest.mark.django_db
def test_pending_document_has_no_searchable_content():
    """Uploaded but not chunked yet: not empty, still not answerable."""

    tenant, _, department, member = build_department_with_guide()

    Document.objects.filter(department=department, is_system=True).delete()

    DocumentFactory(
        department=department,
        tenant=tenant,
        uploaded_by=member,
        title="Still processing",
    )

    body = client_for(member).get(READINESS_URL).json()

    assert body["document_count"] == 1
    assert body["is_empty"] is False
    assert body["has_searchable_content"] is False
    assert body["onboarding_document_id"] is None


@pytest.mark.django_db
def test_counts_ignore_other_departments():
    tenant, admin, department, member = build_department_with_guide("Finance")

    other = create_department(tenant, "Marketing", creator=admin)
    DocumentFactory(
        department=other,
        tenant=tenant,
        uploaded_by=admin,
        title="Campaign brief",
    )

    body = client_for(member).get(READINESS_URL).json()

    assert body["department_id"] == department.id
    assert body["document_count"] == 0
    assert body["is_empty"] is True


@pytest.mark.django_db
def test_readiness_requires_authentication():
    response = APIClient().get(READINESS_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_readiness_requires_a_department():
    user = UserFactory(department=None)

    response = client_for(user).get(READINESS_URL)

    assert response.status_code == 403
    assert "department" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_department_without_a_guide_reports_no_onboarding_id():
    """Old departments that have not been backfilled yet."""

    user = UserFactory()

    body = client_for(user).get(READINESS_URL).json()

    assert body["onboarding_document_id"] is None
    assert body["is_empty"] is True
    assert body["has_searchable_content"] is False
