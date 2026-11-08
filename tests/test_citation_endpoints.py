import pytest

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from api.services import build_citations
from departments.models import Department
from documents.models import Document, DocumentChunk
from tenants.models import Tenant


User = get_user_model()

PASSWORD = "StrongPassword123!"
CHUNK_TEXT = "The launch code for project ORBIT is ORBIT-742."

# Documents created with a real file on disk. Django's storage renames a
# file when the name is taken, so every test must clean up after itself
# or the next run gets `name_XXXX.txt` instead of `name.txt`.
_CREATED_DOCUMENTS = []


@pytest.fixture(autouse=True)
def cleanup_media():
    _CREATED_DOCUMENTS.clear()

    yield

    for document in _CREATED_DOCUMENTS:
        if document.file_path:
            document.file_path.delete(save=False)

    _CREATED_DOCUMENTS.clear()


@pytest.fixture
def organization(db):
    """
    One tenant, two departments, and the users needed to prove that a
    citation can only be opened by someone allowed to read the source.
    """

    tenant = Tenant.objects.create(name="Citation Test Organization")

    it_department = Department.objects.create(name="IT", tenant=tenant)
    hr_department = Department.objects.create(name="HR", tenant=tenant)

    member = User.objects.create_user(
        username="citation_member",
        password=PASSWORD,
        role="Member",
        department=it_department,
        tenant=tenant,
    )

    outsider = User.objects.create_user(
        username="citation_outsider",
        password=PASSWORD,
        role="Member",
        department=hr_department,
        tenant=tenant,
    )

    admin = User.objects.create_user(
        username="citation_admin",
        password=PASSWORD,
        role="Admin",
        department=hr_department,
        tenant=tenant,
    )

    return {
        "tenant": tenant,
        "it": it_department,
        "hr": hr_department,
        "member": member,
        "outsider": outsider,
        "admin": admin,
    }


def make_document(
    organization,
    *,
    with_file=True,
    department=None,
    user=None,
    title="e2e-rag-test.txt",
    file_content=CHUNK_TEXT,
):
    department = department or organization["it"]
    user = user or organization["member"]

    document = Document(
        title=title,
        file_type="text/plain",
        uploaded_by=user,
        department=department,
        tenant=organization["tenant"],
        status="Indexed",
    )

    if with_file:
        document.file_path.save(
            "e2e-rag-test.txt",
            ContentFile(file_content.encode("utf-8")),
            save=False,
        )

    document.save()

    if with_file:
        _CREATED_DOCUMENTS.append(document)

    return document


def stored_filename(document):
    return document.file_path.name.rsplit("/", 1)[-1]


def make_chunk(document, index=0, content=CHUNK_TEXT):
    return DocumentChunk.objects.create(
        document=document,
        content=content,
        chunk_index=index,
    )


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


@pytest.mark.django_db
def test_chunk_detail_returns_the_cited_passage(organization):
    document = make_document(organization)
    chunk = make_chunk(document)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/chunks/{chunk.id}/"
    )

    assert response.status_code == 200
    assert response.data["chunk_id"] == chunk.id
    assert response.data["content"] == CHUNK_TEXT
    assert response.data["chunk_index"] == 0
    assert response.data["document_id"] == document.id
    assert response.data["document_title"] == "e2e-rag-test.txt"
    assert response.data["filename"] == stored_filename(document)
    assert response.data["department"] == "IT"
    assert response.data["file_type"] == "text/plain"
    # Relative to the API base URL: the client prepends ".../api",
    # so a leading "/api" here would produce "/api/api/...".
    assert response.data["file_url"] == f"/documents/{document.id}/file/"
    assert response.data["preview_url"] == f"/documents/{document.id}/preview/"


@pytest.mark.django_db
def test_chunk_detail_rejects_another_department(organization):
    document = make_document(organization)
    chunk = make_chunk(document)

    response = authenticated_client(organization["outsider"]).get(
        f"/api/documents/chunks/{chunk.id}/"
    )

    assert response.status_code == 403
    assert CHUNK_TEXT not in str(response.data)


@pytest.mark.django_db
def test_chunk_detail_hides_chunks_from_another_tenant(organization):
    other_tenant = Tenant.objects.create(name="Citation Other Tenant")
    other_department = Department.objects.create(
        name="IT",
        tenant=other_tenant,
    )
    other_user = User.objects.create_user(
        username="citation_other_tenant_user",
        password=PASSWORD,
        role="Member",
        department=other_department,
        tenant=other_tenant,
    )

    document = make_document(
        organization,
        department=other_department,
        user=other_user,
    )
    chunk = make_chunk(document)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/chunks/{chunk.id}/"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_chunk_detail_requires_authentication(organization):
    document = make_document(organization)
    chunk = make_chunk(document)

    response = APIClient().get(f"/api/documents/chunks/{chunk.id}/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_admin_can_open_a_chunk_from_another_department(organization):
    document = make_document(organization)
    chunk = make_chunk(document)

    response = authenticated_client(organization["admin"]).get(
        f"/api/documents/chunks/{chunk.id}/"
    )

    assert response.status_code == 200
    assert response.data["content"] == CHUNK_TEXT


@pytest.mark.django_db
def test_document_file_serves_the_original_bytes(organization):
    document = make_document(organization)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/{document.id}/file/"
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "inline" in response["Content-Disposition"]
    assert b"ORBIT-742" in b"".join(response.streaming_content)


@pytest.mark.django_db
def test_document_file_blocks_another_department(organization):
    document = make_document(organization)

    response = authenticated_client(organization["outsider"]).get(
        f"/api/documents/{document.id}/file/"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_document_file_returns_404_when_storage_is_empty(organization):
    document = make_document(organization, with_file=False)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/{document.id}/file/"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_build_citations_includes_the_snippet(organization):
    document = make_document(organization)
    chunk = make_chunk(document, index=3)

    citations = build_citations([chunk.id], user=organization["member"])

    assert len(citations) == 1
    assert citations[0]["chunk_id"] == chunk.id
    assert citations[0]["chunk_index"] == 3
    assert citations[0]["title"] == "e2e-rag-test.txt"
    assert citations[0]["snippet"] == CHUNK_TEXT


@pytest.mark.django_db
def test_chunk_detail_highlights_the_matched_terms(organization):
    document = make_document(organization)
    chunk = make_chunk(document)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/chunks/{chunk.id}/",
        {"q": "ORBIT-742"},
    )

    assert response.status_code == 200
    assert response.data["matched_terms"] == ["orbit", "742"]

    content = response.data["content"]
    highlighted = [
        content[start:end] for start, end in response.data["highlights"]
    ]

    assert "ORBIT-742" in highlighted


@pytest.mark.django_db
def test_chunk_detail_returns_no_highlights_without_a_query(organization):
    document = make_document(organization)
    chunk = make_chunk(document)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/chunks/{chunk.id}/"
    )

    assert response.status_code == 200
    assert response.data["highlights"] == []
    assert response.data["matched_terms"] == []


@pytest.mark.django_db
def test_document_preview_returns_the_full_text_with_highlights(organization):
    document = make_document(organization)
    make_chunk(document)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/{document.id}/preview/",
        {"q": "ORBIT-742"},
    )

    assert response.status_code == 200
    assert response.data["document_id"] == document.id
    assert response.data["content"] == CHUNK_TEXT
    assert response.data["truncated"] is False
    assert response.data["matched_terms"] == ["orbit", "742"]

    highlighted = [
        response.data["content"][start:end]
        for start, end in response.data["highlights"]
    ]

    assert "ORBIT-742" in highlighted


@pytest.mark.django_db
def test_document_preview_highlights_every_occurrence(organization):
    document = make_document(
        organization,
        file_content="ORBIT-742 appears twice: ORBIT-742.",
    )
    make_chunk(document, content="ORBIT-742 appears twice.")

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/{document.id}/preview/",
        {"q": "ORBIT-742"},
    )

    assert response.status_code == 200
    assert len(response.data["highlights"]) == 2

    highlighted = [
        response.data["content"][start:end]
        for start, end in response.data["highlights"]
    ]

    assert highlighted == ["ORBIT-742", "ORBIT-742"]


@pytest.mark.django_db
def test_document_preview_is_scoped_to_the_department(organization):
    document = make_document(organization)

    response = authenticated_client(organization["outsider"]).get(
        f"/api/documents/{document.id}/preview/"
    )

    assert response.status_code == 403
    assert CHUNK_TEXT not in str(response.data)


@pytest.mark.django_db
def test_document_preview_returns_415_for_unsupported_types(organization):
    document = make_document(organization)
    Document.objects.filter(pk=document.pk).update(file_type="application/zip")

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/{document.id}/preview/"
    )

    assert response.status_code == 415
    assert "error" in response.data


@pytest.mark.django_db
def test_document_preview_returns_404_when_the_file_is_missing(organization):
    document = make_document(organization, with_file=False)

    response = authenticated_client(organization["member"]).get(
        f"/api/documents/{document.id}/preview/"
    )

    assert response.status_code == 404
