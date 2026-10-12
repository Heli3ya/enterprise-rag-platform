import pytest
from unittest.mock import patch

from documents.chunking import chunk_text, save_document_chunks
from documents.models import DocumentChunk
from tests.factories import DocumentFactory


def test_chunk_text_returns_empty_list_for_blank_text():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


@pytest.mark.parametrize("chunk_size", [299, 501])
def test_chunk_text_rejects_invalid_chunk_size(chunk_size):
    with pytest.raises(
        ValueError,
        match="chunk_size must be between 300 and 500 tokens",
    ):
        chunk_text("example text", chunk_size=chunk_size)


@pytest.mark.parametrize("overlap_percent", [9, 16])
def test_chunk_text_rejects_invalid_overlap(overlap_percent):
    with pytest.raises(
        ValueError,
        match="overlap_percent must be between 10 and 15",
    ):
        chunk_text("example text", overlap_percent=overlap_percent)


def test_chunk_text_splits_long_text_with_overlap():
    text = " ".join(["enterprise"] * 1000)

    chunks = chunk_text(
        text,
        chunk_size=300,
        overlap_percent=10,
    )

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)
    assert all("enterprise" in chunk for chunk in chunks)


@pytest.mark.django_db
def test_save_document_chunks_returns_empty_list_for_blank_text():
    document = DocumentFactory()

    result = save_document_chunks(document, "   ")

    assert result == []
    assert DocumentChunk.objects.filter(document=document).count() == 0


@pytest.mark.django_db
def test_save_document_chunks_saves_chunks_to_database():
    document = DocumentFactory()
    expected_chunks = ["First chunk", "Second chunk"]

    with patch(
        "documents.chunking.chunk_text",
        return_value=expected_chunks,
    ):
        result = save_document_chunks(document, "sample text")

    assert len(result) == 2
    assert DocumentChunk.objects.filter(document=document).count() == 2
    assert result[0].chunk_index == 0
    assert result[1].chunk_index == 1
    assert result[0].content == "First chunk"
    assert result[1].content == "Second chunk"
