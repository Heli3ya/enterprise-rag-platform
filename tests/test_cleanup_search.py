"""
Sub-task 3 — the proof the acceptance criterion asks for.

"Upload a revised version of a regulation, and the RAG engine retrieves
only the clauses of the new version; no trace of the text removed from
the old version appears in the search results."

The first test below is that sentence, executed. The rest isolate the
mechanism: they tombstone a chunk while leaving its document `Indexed`,
which is the only way to show that `is_active` is a guard in its own
right and not a restatement of the status filter.
"""

from unittest.mock import Mock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from api.services import (
    department_has_searchable_content,
    keyword_search,
    semantic_search,
)
from documents.models import Document, DocumentChunk, Embedding
from documents.tasks import (
    cleanup_superseded_document,
    generate_embedding_batch,
    process_document,
)
from tests.factories import (
    DocumentChunkFactory,
    DocumentFactory,
    UserFactory,
)


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def fake_embeddings(texts):
    return [[0.0] * 384 for _ in texts], 384


def index_document(document_id):
    """Run the embedding stage for every chunk of a document."""

    chunk_ids = list(
        DocumentChunk.objects
        .filter(document_id=document_id)
        .values_list("id", flat=True)
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ):
        generate_embedding_batch.run(document_id, chunk_ids)


@pytest.mark.django_db
def test_a_revised_regulation_is_answered_from_the_new_clauses_only(
    django_capture_on_commit_callbacks,
):
    """
    The acceptance scenario, end to end.

    v1 says receipts are due in 30 days and travel needs approval.
    v2 drops the receipts clause entirely and adds a hotel booking
    clause. After the replacement is indexed, the removed clause must
    be unreachable and the surviving one must resolve to v2.
    """

    user = UserFactory()
    client = authenticated_client(user)

    old_text = (
        b"Receipts must be submitted within 30 days. "
        b"All travel must be approved by a manager."
    )
    new_text = (
        b"All travel must be approved by a manager. "
        b"Hotel bookings go through the travel desk."
    )

    with patch(
        "documents.views.process_document.delay",
    ), patch(
        "documents.views.transaction.on_commit",
        side_effect=lambda callback: callback(),
    ):
        upload = client.post(
            "/api/documents/",
            {
                "title": "Travel regulation",
                "department": user.department_id,
                "file_path": SimpleUploadedFile(
                    "regulation-v1.txt",
                    old_text,
                    content_type="text/plain",
                ),
            },
            format="multipart",
        )

    assert upload.status_code == 201
    first_id = upload.data["document_id"]

    with patch("documents.tasks.generate_embedding_batch.delay"):
        process_document.run(first_id)

    index_document(first_id)

    assert Document.objects.get(id=first_id).status == "Indexed"

    version_response = client.post(
        f"/api/documents/{first_id}/versions/",
        {
            "file_path": SimpleUploadedFile(
                "regulation-v2.txt",
                new_text,
                content_type="text/plain",
            )
        },
        format="multipart",
    )

    assert version_response.status_code == 201
    second_id = version_response.data["document_id"]

    with patch("documents.tasks.generate_embedding_batch.delay"):
        process_document.run(second_id)

    with patch("documents.tasks.cleanup_superseded_document.delay"):
        with django_capture_on_commit_callbacks(execute=True):
            index_document(second_id)

    assert Document.objects.get(id=second_id).status == "Indexed"

    cleanup_superseded_document.run(second_id)

    # The clause that was removed in v2 is gone from the answer path.
    assert keyword_search("receipts", user=user).count() == 0

    # The clause that survived resolves to the new version only.
    results = list(keyword_search("approved", user=user))

    assert results
    assert {result.document_id for result in results} == {second_id}

    # And the new clause is reachable.
    new_results = list(keyword_search("desk", user=user))

    assert new_results
    assert {result.document_id for result in new_results} == {second_id}


@pytest.mark.django_db
def test_no_vector_survives_for_the_superseded_version():
    user = UserFactory()
    old = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel regulation",
        status="Archived",
    )
    old_chunk = DocumentChunkFactory(
        document=old,
        chunk_index=0,
        content="Receipts must be submitted within 30 days.",
    )
    Embedding.objects.create(
        chunk=old_chunk,
        embedding_vector=[0.0] * 384,
        model_name="test-embedding-model",
    )
    new = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel regulation",
        status="Indexed",
        version=2,
        parent_document=old,
    )
    DocumentChunkFactory(
        document=new,
        chunk_index=0,
        content="Receipts must be submitted within 14 days.",
    )

    cleanup_superseded_document.run(new.id)

    assert Embedding.objects.filter(chunk__document_id=old.id).count() == 0


@pytest.mark.django_db
def test_keyword_search_ignores_a_tombstoned_chunk():
    """
    The document is still `Indexed`; only the chunk is tombstoned.

    This is the state a restored version would be in if the tombstone
    were forgotten, and it is why `is_active` is checked separately
    instead of being derived from the status.
    """

    user = UserFactory()
    document = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel regulation",
        status="Indexed",
    )
    chunk = DocumentChunkFactory(
        document=document,
        chunk_index=0,
        content="Receipts must be submitted within 30 days.",
    )

    assert keyword_search("receipts", user=user).count() == 1

    DocumentChunk.objects.filter(id=chunk.id).update(is_active=False)

    assert keyword_search("receipts", user=user).count() == 0


@pytest.mark.django_db
def test_the_cold_start_gate_ignores_tombstoned_chunks():
    user = UserFactory()
    document = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel regulation",
        status="Indexed",
    )
    chunk = DocumentChunkFactory(
        document=document,
        chunk_index=0,
        content="Receipts must be submitted within 30 days.",
    )

    assert department_has_searchable_content(user) is True

    DocumentChunk.objects.filter(id=chunk.id).update(is_active=False)

    # No live chunk means nothing to answer from, so the gate must stop
    # the request before it reaches an LLM with no sources.
    assert department_has_searchable_content(user) is False


@pytest.mark.django_db
def test_vector_search_drops_tombstoned_chunks():
    user = UserFactory()
    document = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel regulation",
        status="Indexed",
    )
    chunk = DocumentChunkFactory(
        document=document,
        chunk_index=0,
        content="Receipts must be submitted within 30 days.",
    )

    DocumentChunk.objects.filter(id=chunk.id).update(is_active=False)

    response = Mock()
    response.json.return_value = {
        "results": [
            {
                "chunk_id": chunk.id,
                "distance": 0.1,
                "content": chunk.content,
                "chunk_index": 0,
            }
        ]
    }

    with patch("api.services.requests.post", return_value=response):
        results = semantic_search("receipts", user=user)

    assert results == []


@pytest.mark.django_db
def test_a_purged_version_is_not_counted_by_the_readiness_endpoint():
    user = UserFactory()
    old = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel regulation",
        status="Archived",
    )
    old_chunk = DocumentChunkFactory(
        document=old,
        chunk_index=0,
        content="Receipts must be submitted within 30 days.",
    )
    new = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel regulation",
        status="Indexed",
        version=2,
        parent_document=old,
    )

    cleanup_superseded_document.run(new.id)

    response = authenticated_client(user).get("/api/departments/readiness/")

    assert response.status_code == 200
    assert response.data["document_count"] == 1
    assert response.data["has_searchable_content"] is False
    assert DocumentChunk.objects.filter(id=old_chunk.id).exists()
