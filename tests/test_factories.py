import pytest

from tests.factories import (
    AdminFactory,
    DepartmentFactory,
    DocumentChunkFactory,
    DocumentFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_department_factory_creates_unique_departments():
    department_a = DepartmentFactory()
    department_b = DepartmentFactory()

    assert department_a.pk is not None
    assert department_b.pk is not None
    assert department_a.name != department_b.name


@pytest.mark.django_db
def test_user_factories_create_member_and_admin():
    member = UserFactory()
    admin = AdminFactory()

    assert member.pk is not None
    assert member.role == "Member"
    assert member.check_password("TestPassword123!")

    assert admin.pk is not None
    assert admin.role == "Admin"
    assert admin.check_password("TestPassword123!")


@pytest.mark.django_db
def test_document_factory_uses_owner_department():
    document = DocumentFactory()

    assert document.pk is not None
    assert document.uploaded_by.pk is not None
    assert document.department_id == document.uploaded_by.department_id


@pytest.mark.django_db
def test_document_chunk_factory_creates_chunk():
    chunk = DocumentChunkFactory()

    assert chunk.pk is not None
    assert chunk.document.pk is not None
    assert chunk.content
    assert chunk.chunk_index == 0
