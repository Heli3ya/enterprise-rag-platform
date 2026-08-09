import tiktoken
from django.db import transaction
from documents.models import DocumentChunk
def chunk_text(
    text: str,
    chunk_size: int = 400,
    overlap_percent: int = 10,
) -> list[str]:
    """
    Split text into token-based chunks with configurable overlap.
    Args:
        text: The extracted document text.
        chunk_size: Target number of tokens per chunk.
        overlap_percent: Overlap percentage between chunks.
    Returns:
        A list of text chunks.
    """
    if not text.strip():
        return []
    if not 300 <= chunk_size <= 500:
        raise ValueError("chunk_size must be between 300 and 500 tokens.")
    if not 10 <= overlap_percent <= 15:
        raise ValueError("overlap_percent must be between 10 and 15.")
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    overlap_tokens = int(chunk_size * overlap_percent / 100)
    step = chunk_size - overlap_tokens
    chunks = []
    for start in range(0, len(tokens), step):
        chunk_tokens = tokens[start:start + chunk_size]
        if not chunk_tokens:
            break
        chunk = encoding.decode(chunk_tokens)
        if chunk.strip():
            chunks.append(chunk.strip())
        if start + chunk_size >= len(tokens):
            break
    return chunks
def save_document_chunks(
    document,
    text: str,
    chunk_size: int = 400,
    overlap_percent: int = 10,
) -> list[DocumentChunk]:
    """
    Create and save document chunks in the database.
    Args:
        document: The Document instance the chunks belong to.
        text: Extracted document text.
        chunk_size: Target chunk size in tokens.
        overlap_percent: Overlap percentage between chunks.
    Returns:
        The created DocumentChunk instances.
    """
    chunks = chunk_text(
        text=text,
        chunk_size=chunk_size,
        overlap_percent=overlap_percent,
    )
    if not chunks:
        return []
    chunk_objects = [
        DocumentChunk(
            document=document,
            content=chunk,
            chunk_index=index,
        )
        for index, chunk in enumerate(chunks)
    ]
    with transaction.atomic():
        DocumentChunk.objects.bulk_create(chunk_objects)
    return chunk_objects