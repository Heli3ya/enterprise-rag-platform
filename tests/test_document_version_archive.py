"""
Sub-task 3 — archiving the old version, and the search engine's view.

The acceptance criterion is not "a status field changed". It is that
the retrieval pipeline stops citing the superseded document. These
tests therefore check the three doors a stale version could come
through: keyword search, vector search, and the cold-start gate that
decides whether the pipeline runs at all — plus the two background
tasks that could resurrect it after the fact.
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from api.services import (
    build_citations,
    department_has_searchable_content,
    keyword_search,
    semantic_search,
)
from documents.models import Document, DocumentChunk, Embedding
from documents.tasks import generate_embedding_batch, process_document
from documents.versioning import archive_document
from tests.factories import (
    AdminFactory,
    DocumentChunkFactory,
    DocumentFactory,
    UserFactory,
)


def indexed_document(user, title, content):
    document = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title=title,
        status="Indexed",
    )
    chunk = DocumentChunkFactory(
        document=document,
        chunk_index=0,
        content=content,
    )
    Embedding.objects.create(
        chunk=chunk,
        embedding_vector=[0.0] * 384,
        model_name="test-embedding-model",
    )

    return document, chunk


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


@pytest.mark.django_db
def test_keyword_search_stops_finding_an_archived_version():
    user = UserFactory()
    document, _ = indexed_document(
        user,
        "Travel policy",
        "Receipts for travel expenses must be submitted within 30 days.",
    )

    assert keyword_search("receipts", user=user).count() == 1

    archive_document(document)

    assert keyword_search("receipts", user=user).count() == 0


@pytest.mark.django_db
def test_keyword_search_finds_the_replacement_instead():
    user = UserFactory()
    old, _ = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )
    new, _ = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 14 days.",
    )

    archive_document(old)

    results = list(keyword_search("receipts", user=user))

    assert len(results) == 1
    assert results[0].document_id == new.id


@pytest.mark.django_db
def test_the_cold_start_gate_ignores_archived_documents():
    user = UserFactory()
    document, _ = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )

    assert department_has_searchable_content(user) is True

    archive_document(document)

    # A department whose only document was superseded has nothing to
    # answer from — the gate must say so instead of letting the request
    # reach an LLM with no sources.
    assert department_has_searchable_content(user) is False


@pytest.mark.django_db
def test_the_readiness_endpoint_does_not_count_archived_versions():
    user = UserFactory()
    document, _ = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )
    archive_document(document)

    response = authenticated_client(user).get("/api/departments/readiness/")

    assert response.status_code == 200
    assert response.data["document_count"] == 0
    assert response.data["has_searchable_content"] is False
    assert response.data["is_empty"] is True


@pytest.mark.django_db
def test_admin_analytics_does_not_count_archived_versions():
    admin = AdminFactory()
    document, _ = indexed_document(
        admin,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )
    archive_document(document)

    response = authenticated_client(admin).get("/api/admin/analytics/")

    assert response.status_code == 200
    assert response.data["total_documents"] == 0


@pytest.mark.django_db
def test_vector_search_drops_chunks_belonging_to_archived_documents():
    user = UserFactory()
    document, chunk = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )
    archive_document(document)

    from unittest.mock import Mock

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
def test_process_document_refuses_to_resurrect_an_archived_document():
    user = UserFactory()
    document, _ = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )
    archive_document(document)

    result = process_document.run(document.id)

    document.refresh_from_db()

    assert result["skipped"] == "archived"
    assert document.status == "Archived"


@pytest.mark.django_db
def test_an_embedding_batch_cannot_revive_an_archived_document():
    user = UserFactory()
    document, chunk = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )
    archive_document(document)

    with patch("documents.tasks.generate_embeddings") as generate:
        result = generate_embedding_batch.run(document.id, [chunk.id])

    document.refresh_from_db()

    assert result["skipped"] == "archived"
    assert document.status == "Archived"
    assert Embedding.objects.count() == 0
    # No inference is paid for an obsolete version.
    generate.assert_not_called()


@pytest.mark.django_db
def test_a_batch_that_finishes_after_archiving_drops_its_own_vectors():
    """
    The awkward interleaving: the batch passes its first check, then a
    new version is uploaded while the embedding model is still running.

    Archiving locks the document row; this path locks it too before
    deciding, so whichever commits second sees the other's result and
    removes the vectors it just wrote.
    """

    user = UserFactory()
    document = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Travel policy",
        status="Indexed",
    )
    chunk = DocumentChunkFactory(
        document=document,
        chunk_index=0,
        content="Receipts must be submitted within 30 days.",
    )

    def archive_while_embedding(texts):
        archive_document(Document.objects.get(id=document.id))

        return [[0.0] * 384 for _ in texts], 384

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=archive_while_embedding,
    ):
        result = generate_embedding_batch.run(document.id, [chunk.id])

    assert result["skipped"] == "archived"
    assert Embedding.objects.filter(chunk=chunk).count() == 0


@pytest.mark.django_db
def test_citations_of_earlier_answers_still_resolve_after_archiving():
    user = UserFactory()
    document, chunk = indexed_document(
        user,
        "Travel policy",
        "Receipts must be submitted within 30 days.",
    )
    archive_document(document)

    citations = build_citations([chunk.id], user=user)

    # History is not rewritten: the passage the user was shown last
    # month still opens.
    assert len(citations) == 1
    assert citations[0]["document_id"] == document.id


@pytest.mark.django_db
def test_the_new_version_is_what_the_search_engine_cites(tmp_path):
    """
    End to end: v1 says 30 days, v2 says 14, and only v2 is findable.

    Goes through the real upload, the real chunker and the real keyword
    search; only the embedding model call is faked.
    """

    user = UserFactory()
    client = authenticated_client(user)

    old_text = b"Travel receipts must be submitted within 30 days."
    new_text = b"Travel receipts must be submitted within 14 days."

    with patch(
        "documents.views.process_document.delay",
    ), patch(
        "documents.views.transaction.on_commit",
        side_effect=lambda callback: callback(),
    ):
        upload = client.post(
            "/api/documents/",
            {
                "title": "Travel policy",
                "department": user.department_id,
                "file_path": SimpleUploadedFile(
                    "travel-v1.txt",
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

    Document.objects.filter(id=first_id).update(status="Indexed")

    version_response = client.post(
        f"/api/documents/{first_id}/versions/",
        {
            "file_path": SimpleUploadedFile(
                "travel-v2.txt",
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

    assert Document.objects.get(id=first_id).status == "Archived"

    results = list(keyword_search("receipts", user=user))

    assert results, "the new version should be searchable"
    assert {result.document_id for result in results} == {second_id}

    # And the old text really is gone from the answer path.
    archived_chunk_ids = list(
        DocumentChunk.objects
        .filter(document_id=first_id)
        .values_list("id", flat=True)
    )

    assert archived_chunk_ids, "the old text is kept for history"
    assert not any(
        result.id in archived_chunk_ids for result in results
    )
