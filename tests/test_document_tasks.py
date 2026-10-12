import pytest
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import override_settings

from documents.models import DocumentChunk, Embedding
from documents.tasks import (
    generate_embedding_batch,
    process_document,
)
from tests.factories import DocumentFactory, DocumentChunkFactory


@pytest.mark.django_db
def test_process_document_marks_unsupported_file_type_as_failed(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = DocumentFactory(file_type="application/json")
        document.file_path.save(
            "unsupported.json",
            ContentFile(b'{"example": true}'),
            save=True,
        )

        with pytest.raises(
            ValueError,
            match="Unsupported file type",
        ):
            process_document.run(document.pk)

        document.refresh_from_db()
        assert document.status == "Failed"


@pytest.mark.django_db
def test_process_document_marks_empty_chunks_as_failed(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = DocumentFactory(file_type="text/plain")
        document.file_path.save(
            "empty.txt",
            ContentFile(b"Example text"),
            save=True,
        )

        with (
            patch(
                "documents.tasks.extract_txt_text",
                return_value="Example text",
            ),
            patch(
                "documents.tasks.chunk_text",
                return_value=[],
            ),
        ):
            with pytest.raises(
                ValueError,
                match="No text chunks were generated",
            ):
                process_document.run(document.pk)

        document.refresh_from_db()
        assert document.status == "Failed"
        assert not DocumentChunk.objects.filter(
            document=document
        ).exists()


@pytest.mark.django_db
def test_generate_embedding_batch_returns_zero_for_missing_chunks():
    result = generate_embedding_batch.run(
        document_id=999999,
        chunk_ids=[],
    )

    assert result == {
        "document_id": 999999,
        "count": 0,
    }


@pytest.mark.django_db
def test_generate_embedding_batch_rejects_mismatched_vector_count():
    chunk = DocumentChunkFactory()
    document_id = chunk.document_id

    with patch(
        "documents.tasks.generate_embeddings",
        return_value=([], 384),
    ):
        with pytest.raises(
            ValueError,
            match="Embedding count does not match chunk count",
        ):
            generate_embedding_batch.run(
                document_id,
                [chunk.pk],
            )

    assert not Embedding.objects.filter(chunk=chunk).exists()
