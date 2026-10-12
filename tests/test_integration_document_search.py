
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from documents.models import Document, DocumentChunk, Embedding
from documents.tasks import generate_embedding_batch, process_document
from tests.factories import UserFactory


@pytest.mark.django_db
def test_login_upload_process_and_keyword_search(tmp_path):
    """
    Integration test:
    login -> JWT -> upload TXT -> process document ->
    save embeddings -> keyword search.

    Database operations, text extraction, chunk creation and keyword
    search are real. Calls to external AI services are mocked.
    """

    client = APIClient()
    user = UserFactory()

    with override_settings(MEDIA_ROOT=tmp_path):

        # 1. Log in and obtain a JWT access token.
        login_response = client.post(
            "/api/auth/login/",
            {
                "username": user.username,
                "password": "TestPassword123!",
            },
            format="json",
        )

        assert login_response.status_code == 200
        assert "access" in login_response.data

        access_token = login_response.data["access"]

        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}"
        )

        # 2. Upload a real TXT file.
        file_content = (
            "The quartzbridge project stores integration records. "
            "The quartzbridge keyword should be searchable."
        )

        uploaded_file = SimpleUploadedFile(
            "integration_quartzbridge.txt",
            file_content.encode("utf-8"),
            content_type="text/plain",
        )

        # Execute the on_commit callback immediately in this test.
        # Celery's delay method remains mocked, so no worker is started.
        with patch(
            "documents.views.process_document.delay"
        ) as queued_task:
            with patch(
                "documents.views.transaction.on_commit",
                side_effect=lambda callback: callback(),
            ):
                upload_response = client.post(
                    "/api/documents/",
                    {
                        "title": "Quartzbridge Integration Test",
                        "department": user.department_id,
                        "file_path": uploaded_file,
                    },
                    format="multipart",
                )

        assert upload_response.status_code == 201
        assert upload_response.data["status"] == "Pending"
        queued_task.assert_called_once()

        document_id = upload_response.data["document_id"]

        document = Document.objects.get(pk=document_id)

        assert document.uploaded_by_id == user.pk
        assert document.department_id == user.department_id
        assert document.file_type == "text/plain"
        assert document.file_size > 0

        # 3. Process the uploaded file and create real database chunks.
        # Prevent Celery from starting a separate worker.
        with patch(
            "documents.tasks.generate_embedding_batch.delay"
        ):
            processing_result = process_document.run(document_id)

        assert processing_result["document_id"] == document_id
        assert processing_result["chunks_created"] > 0

        chunks = list(
            DocumentChunk.objects.filter(
                document_id=document_id
            ).order_by("chunk_index")
        )

        assert chunks
        assert any(
            "quartzbridge" in chunk.content.lower()
            for chunk in chunks
        )

        # 4. Persist test embeddings without calling the AI service.
        chunk_ids = [chunk.pk for chunk in chunks]
        fake_vectors = [[0.0] * 384 for _ in chunks]

        with patch(
            "documents.tasks.generate_embeddings",
            return_value=(fake_vectors, 384),
        ):
            embedding_result = generate_embedding_batch.run(
                document_id,
                chunk_ids,
            )

        assert embedding_result["chunks_processed"] == len(chunks)

        assert Embedding.objects.filter(
            chunk__document_id=document_id
        ).count() == len(chunks)

        document.refresh_from_db()
        assert document.status == "Indexed"

        # 5. Keep PostgreSQL keyword search real.
        # Mock semantic search and external AI reranking only.
        def fake_rerank_results(query, results):
            return [
                {
                    **result,
                    "rerank_score": 1.0,
                }
                for result in results
            ]

        with (
            patch(
                "api.services.semantic_search",
                return_value=[],
            ),
            patch(
                "api.services.rerank_results",
                side_effect=fake_rerank_results,
            ),
        ):
            search_response = client.post(
                "/api/query/search/",
                {
                    "query_text": "quartzbridge",
                    "top_k": 5,
                },
                format="json",
            )

        assert search_response.status_code == 200
        assert search_response.data["query_text"] == "quartzbridge"

        results = search_response.data["results"]

        assert results
        assert any(
            result["document_id"] == document_id
            and "quartzbridge" in result["content"].lower()
            for result in results
        )
