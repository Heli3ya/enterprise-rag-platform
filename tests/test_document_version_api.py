"""
Sub-task 2 — `POST /api/documents/{id}/versions/`.

The endpoint has to do three things at once: create the replacement,
point it at the version it replaces, and refuse the cases where a new
version would corrupt the chain (an already-superseded parent, a
concurrent upload, another department, another tenant).
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from api.models import AuditLog
from documents.models import Document
from tests.factories import (
    AdminFactory,
    DepartmentFactory,
    DocumentFactory,
    TenantFactory,
    UserFactory,
)


def text_file(name="policy-v2.txt", content=b"Updated travel policy."):
    return SimpleUploadedFile(name, content, content_type="text/plain")


def png_file():
    return SimpleUploadedFile(
        "diagram.png",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        content_type="image/png",
    )


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def current_document(user, **overrides):
    values = {
        "uploaded_by": user,
        "department": user.department,
        "tenant": user.tenant,
        "status": "Indexed",
        "title": "Travel policy",
    }
    values.update(overrides)

    return DocumentFactory(**values)


@pytest.mark.django_db
def test_uploading_a_new_version_creates_v2_linked_to_v1(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    with patch("documents.views.process_document.delay") as queued:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                f"/api/documents/{first.id}/versions/",
                {"file_path": text_file()},
                format="multipart",
            )

    assert response.status_code == 201
    assert response.data["version"] == 2
    assert response.data["parent_document_id"] == first.id
    assert response.data["archived_document_id"] == first.id
    assert response.data["status"] == "Pending"

    second = Document.objects.get(pk=response.data["document_id"])

    assert second.parent_document_id == first.id
    assert second.version == 2
    assert second.department_id == first.department_id
    assert second.tenant_id == first.tenant_id
    assert second.file_size > 0
    assert second.file_type == "text/plain"

    queued.assert_called_once_with(second.id)


@pytest.mark.django_db
def test_the_new_version_inherits_the_title_of_the_one_it_replaces():
    user = UserFactory()
    first = current_document(user, title="Notice period")
    client = authenticated_client(user)

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert response.status_code == 201

    second = Document.objects.get(pk=response.data["document_id"])

    assert second.title == "Notice period"


@pytest.mark.django_db
def test_an_explicit_title_overrides_the_inherited_one():
    user = UserFactory()
    first = current_document(user, title="Notice period")
    client = authenticated_client(user)

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file(), "title": "Notice period (2026)"},
        format="multipart",
    )

    assert response.status_code == 201
    assert Document.objects.get(
        pk=response.data["document_id"],
    ).title == "Notice period (2026)"


@pytest.mark.django_db
def test_a_third_version_chains_from_the_second():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    second_response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )
    second_id = second_response.data["document_id"]

    third_response = client.post(
        f"/api/documents/{second_id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert third_response.status_code == 201
    assert third_response.data["version"] == 3

    third = Document.objects.get(pk=third_response.data["document_id"])

    assert third.parent_document_id == second_id
    assert Document.objects.get(pk=second_id).status == "Archived"


@pytest.mark.django_db
def test_uploading_a_version_of_an_archived_document_is_rejected():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    second_response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    # The first version is now archived; asking it for another child
    # would fork the chain.
    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert response.status_code == 409
    assert str(second_response.data["document_id"]) in response.data["error"]


@pytest.mark.django_db
def test_a_member_of_another_department_cannot_upload_a_version():
    tenant = TenantFactory()
    department_a = DepartmentFactory(tenant=tenant)
    department_b = DepartmentFactory(tenant=tenant)

    owner = UserFactory(department=department_a)
    outsider = UserFactory(department=department_b)
    first = current_document(owner)

    client = authenticated_client(outsider)

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert response.status_code == 403
    assert Document.objects.filter(parent_document=first).count() == 0


@pytest.mark.django_db
def test_an_admin_can_version_a_document_from_another_department():
    tenant = TenantFactory()
    department_a = DepartmentFactory(tenant=tenant)
    department_b = DepartmentFactory(tenant=tenant)

    owner = UserFactory(department=department_a)
    admin = AdminFactory(department=department_b)
    first = current_document(owner)

    client = authenticated_client(admin)

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_another_tenant_gets_a_404():
    owner = UserFactory()
    stranger = UserFactory()
    first = current_document(owner)

    client = authenticated_client(stranger)

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_a_system_document_cannot_be_versioned():
    user = UserFactory()
    guide = current_document(user, is_system=True)
    client = authenticated_client(user)

    response = client.post(
        f"/api/documents/{guide.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert response.status_code == 400
    assert Document.objects.filter(parent_document=guide).count() == 0


@pytest.mark.django_db
def test_an_unsupported_file_type_is_rejected():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": png_file()},
        format="multipart",
    )

    assert response.status_code == 400
    assert Document.objects.filter(parent_document=first).count() == 0


@pytest.mark.django_db
def test_an_oversized_file_is_rejected():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    big_file = SimpleUploadedFile(
        "huge.txt",
        b"a" * (5 * 1024 * 1024 + 1),
        content_type="text/plain",
    )

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": big_file},
        format="multipart",
    )

    assert response.status_code == 400
    assert Document.objects.filter(parent_document=first).count() == 0


@pytest.mark.django_db
def test_a_duplicate_version_number_is_reported_as_a_conflict():
    user = UserFactory()
    first = current_document(user)

    # A v2 that exists without the parent being archived — the shape a
    # concurrent upload leaves behind for a moment.
    DocumentFactory(
        uploaded_by=user,
        department=first.department,
        tenant=first.tenant,
        title=first.title,
        version=2,
        parent_document=first,
        status="Indexed",
    )

    client = authenticated_client(user)

    response = client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert response.status_code == 409
    assert Document.objects.filter(parent_document=first).count() == 1


@pytest.mark.django_db
def test_the_version_list_returns_the_chain_oldest_first():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    response = client.get(f"/api/documents/{first.id}/versions/")

    assert response.status_code == 200
    assert response.data["version"] == 1
    assert [item["version"] for item in response.data["versions"]] == [1, 2]
    assert response.data["latest_document_id"] == response.data["versions"][1]["id"]


@pytest.mark.django_db
def test_only_the_newest_version_is_marked_current():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    response = client.get(f"/api/documents/{first.id}/versions/")

    flags = [item["is_current"] for item in response.data["versions"]]

    assert flags == [False, True]
    assert response.data["versions"][0]["status"] == "Archived"


@pytest.mark.django_db
def test_the_upload_is_written_to_the_audit_log():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    assert AuditLog.objects.filter(
        user=user,
        action="VERSION",
    ).count() == 1


@pytest.mark.django_db
def test_the_document_list_hides_archived_versions_by_default():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    response = client.get("/api/documents/")

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["version"] == 2
    assert response.data[0]["status"] == "Pending"


@pytest.mark.django_db
def test_the_document_list_can_include_archived_versions():
    user = UserFactory()
    first = current_document(user)
    client = authenticated_client(user)

    client.post(
        f"/api/documents/{first.id}/versions/",
        {"file_path": text_file()},
        format="multipart",
    )

    response = client.get("/api/documents/?include_archived=true")

    assert response.status_code == 200
    assert sorted(item["version"] for item in response.data) == [1, 2]
