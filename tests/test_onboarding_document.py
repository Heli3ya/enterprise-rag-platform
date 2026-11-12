"""
Sub-task 2 — every new department is born with a guide.

The guarantee is "a department created through any path ends up with one
searchable onboarding document". That covers the API, the model layer
(admin, shell, fixtures), the backfill command, and the failure modes:
no user to attribute it to, a broker that is down, and a second call
that must not duplicate the guide.
"""

from unittest.mock import patch

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from api.services import keyword_search
from departments.models import Department
from documents.models import Document, DocumentChunk
from documents.onboarding import (
    ONBOARDING_TITLE_PREFIX,
    build_onboarding_text,
    ensure_onboarding_document,
    onboarding_title,
)
from tests.factories import (
    AdminFactory,
    DepartmentFactory,
    TenantFactory,
    UserFactory,
    create_department,
)


CREATE_URL = "/api/departments/create/"


def guide_for(department):
    return Document.objects.filter(department=department, is_system=True).first()


@pytest.mark.django_db
def test_creating_a_department_through_the_api_seeds_the_guide():
    admin = AdminFactory()

    client = APIClient()
    client.force_authenticate(user=admin)

    response = client.post(
        CREATE_URL,
        {"name": "Finance", "description": "Budget and reporting"},
        format="json",
    )

    assert response.status_code == 201

    department = Department.objects.get(id=response.json()["id"])
    guide = guide_for(department)

    assert guide is not None
    assert guide.is_system is True
    assert guide.title.startswith(ONBOARDING_TITLE_PREFIX)
    assert "Finance" in guide.title
    assert guide.tenant_id == admin.tenant_id
    assert guide.uploaded_by_id == admin.id
    assert guide.file_type == "text/plain"

    # A guide without chunks would be invisible to search, which is the
    # only thing that makes it useful.
    assert DocumentChunk.objects.filter(document=guide).count() > 0
    assert guide.file_path.storage.exists(guide.file_path.name)


@pytest.mark.django_db
def test_guide_is_attributed_to_the_creating_admin_not_an_arbitrary_one():
    tenant = TenantFactory()
    other_admin = AdminFactory(tenant=tenant, department=None)
    creator = AdminFactory(tenant=tenant, department=None)

    department = create_department(tenant, "Legal", creator=creator)

    guide = guide_for(department)

    assert guide.uploaded_by_id == creator.id
    assert guide.uploaded_by_id != other_admin.id


@pytest.mark.django_db
def test_signal_falls_back_to_the_tenant_admin():
    """Departments created outside the API still get a guide."""

    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)

    department = Department.objects.create(tenant=tenant, name="Operations")

    guide = guide_for(department)

    assert guide is not None
    assert guide.uploaded_by_id == admin.id


@pytest.mark.django_db
def test_department_without_any_user_is_skipped_quietly():
    tenant = TenantFactory()

    department = Department.objects.create(tenant=tenant, name="Ghost")

    assert Department.objects.filter(id=department.id).exists()
    assert guide_for(department) is None


@pytest.mark.django_db
def test_guide_is_created_only_once():
    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)
    department = Department.objects.create(tenant=tenant, name="Sales")

    assert ensure_onboarding_document(department, created_by=admin) is None

    assert Document.objects.filter(department=department, is_system=True).count() == 1
    assert DocumentChunk.objects.filter(document__department=department).count() > 0


@pytest.mark.django_db
def test_guide_is_findable_by_keyword_search():
    """The guide must be reachable even before embeddings exist."""

    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)
    department = create_department(tenant, "Support", creator=admin)

    member = UserFactory(tenant=tenant, department=department)

    results = keyword_search("PDF", limit=5, user=member)

    assert results
    assert all(
        result.document.department_id == department.id
        for result in results
    )
    assert any("آپلود" in result.content for result in results)


@pytest.mark.django_db
def test_guide_does_not_count_as_user_content():
    user = UserFactory()
    create_department(user.tenant, "Research", creator=user)

    assert Document.objects.filter(
        department__tenant=user.tenant,
        is_system=True,
    ).exists()

    assert Document.objects.filter(
        department__tenant=user.tenant,
        is_system=False,
    ).count() == 0


@pytest.mark.django_db
def test_embeddings_are_enqueued_after_commit(django_capture_on_commit_callbacks):
    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        department = create_department(tenant, "Data", creator=admin)

    # Nothing may be queued while the transaction is still open.
    assert len(callbacks) == 1

    with patch("documents.tasks.generate_embedding_batch.delay") as delay:
        for callback in callbacks:
            callback()

    delay.assert_called()
    assert delay.call_args.args[0] == guide_for(department).id


@pytest.mark.django_db
def test_broker_outage_keeps_the_guide_searchable(django_capture_on_commit_callbacks):
    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        department = create_department(tenant, "Logistics", creator=admin)

    member = UserFactory(tenant=tenant, department=department)

    with patch(
        "documents.tasks.generate_embedding_batch.delay",
        side_effect=RuntimeError("broker is down"),
    ):
        # Must not raise: a failed enqueue cannot undo the department.
        for callback in callbacks:
            callback()

    guide = guide_for(department)

    assert guide is not None
    assert guide.chunks.exists()
    assert keyword_search("DOCX", limit=5, user=member)


@pytest.mark.django_db
def test_signal_can_be_skipped_explicitly():
    """
    Escape hatch for fixtures and data migrations that want a department
    with no guide (for example to reproduce a legacy state).
    """

    tenant = TenantFactory()
    AdminFactory(tenant=tenant, department=None)

    department = Department(tenant=tenant, name="No Guide")
    department._skip_onboarding = True
    department.save()

    assert guide_for(department) is None


@pytest.mark.django_db
def test_management_command_backfills_missing_guides():
    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)
    department = Department.objects.create(tenant=tenant, name="Legacy")

    # Simulate a department that predates the feature.
    Document.objects.filter(department=department, is_system=True).delete()

    assert guide_for(department) is None

    call_command("seed_onboarding_docs", tenant_id=tenant.id, verbosity=0)

    guide = guide_for(department)

    assert guide is not None
    assert guide.chunks.exists()


@pytest.mark.django_db
def test_backfill_command_is_idempotent():
    tenant = TenantFactory()
    admin = AdminFactory(tenant=tenant, department=None)
    create_department(tenant, "Existing", creator=admin)

    call_command("seed_onboarding_docs", verbosity=0)
    call_command("seed_onboarding_docs", verbosity=0)

    assert Document.objects.filter(is_system=True, tenant=tenant).count() == 1


@pytest.mark.django_db
def test_dry_run_writes_nothing():
    tenant = TenantFactory()
    AdminFactory(tenant=tenant, department=None)
    department = Department.objects.create(tenant=tenant, name="Planned")

    Document.objects.filter(department=department).delete()

    call_command("seed_onboarding_docs", tenant_id=tenant.id, dry_run=True, verbosity=0)

    assert guide_for(department) is None


def test_guide_text_covers_the_first_day_questions():
    """Cheap, DB-free check of the content contract."""

    department = DepartmentFactory.build(name="Finance")

    text = build_onboarding_text(department)

    assert onboarding_title(department).startswith(ONBOARDING_TITLE_PREFIX)
    assert "Finance" in text

    for term in ("آپلود", "PDF", "DOCX", "TXT", "Indexed", "استناد", "حریم خصوصی"):
        assert term in text

    # The guide must not contain a bracketed number: extract_citation_ids()
    # treats `[12]` as a citation and would resolve it to an unrelated chunk.
    assert not any(
        character.isdigit() and index > 0 and text[index - 1] == "["
        for index, character in enumerate(text)
    )
