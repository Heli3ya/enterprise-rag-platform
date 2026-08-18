from celery import shared_task
from django.db import transaction

from api.services import generate_embeddings

from .models import Document, DocumentChunk, Embedding
from .chunking import chunk_text
from .extractors.pdf import extract_pdf_text
from .extractors.txt import extract_txt_text
from .extractors.word import extract_word_text


EMBEDDING_BATCH_SIZE = 16


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
)
def process_document(document_id: int):
    """
    Extract, chunk, store chunks, and enqueue embedding batches.
    """

    document = None

    try:
        document = Document.objects.get(id=document_id)

        document.status = "Processing"
        document.save(update_fields=["status"])

        with document.file_path.open("rb") as file:
            if document.file_type == "application/pdf":
                extracted_text = extract_pdf_text(file)

            elif document.file_type == "text/plain":
                extracted_text = extract_txt_text(file)

            elif document.file_type in (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
            ):
                extracted_text = extract_word_text(file)

            else:
                raise ValueError(
                    f"Unsupported file type: {document.file_type}"
                )

        chunks = chunk_text(
            extracted_text,
            chunk_size=400,
            overlap_percent=10,
        )

        if not chunks:
            raise ValueError("No text chunks were generated.")

        with transaction.atomic():
            DocumentChunk.objects.filter(
                document=document
            ).delete()

            chunk_objects = [
                DocumentChunk(
                    document=document,
                    content=chunk,
                    chunk_index=index,
                )
                for index, chunk in enumerate(chunks)
            ]

            DocumentChunk.objects.bulk_create(chunk_objects)

        chunk_ids = list(
            DocumentChunk.objects.filter(
                document=document
            ).values_list("id", flat=True)
        )

        for start in range(0, len(chunk_ids), EMBEDDING_BATCH_SIZE):
            batch_ids = chunk_ids[
                start:start + EMBEDDING_BATCH_SIZE
            ]

            generate_embedding_batch.delay(
                document.id,
                batch_ids,
            )

        return {
            "document_id": document.id,
            "chunks_created": len(chunk_ids),
            "batches_created": (
                (len(chunk_ids) + EMBEDDING_BATCH_SIZE - 1)
                // EMBEDDING_BATCH_SIZE
            ),
            "status": document.status,
        }

    except Exception:
        if document is not None:
            try:
                document.status = "Failed"
                document.save(update_fields=["status"])
            except Exception:
                pass

        raise
@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
)
def generate_embedding_batch(document_id: int, chunk_ids: list[int]):
    """
    Generate embeddings for one batch and mark the document as Indexed
    after all chunks have embeddings.
    """

    chunks = list(
        DocumentChunk.objects.filter(
            id__in=chunk_ids,
            document_id=document_id,
        ).order_by("chunk_index")
    )

    if not chunks:
        return {
            "document_id": document_id,
            "count": 0,
        }

    texts = [chunk.content for chunk in chunks]

    vectors, dimension = generate_embeddings(texts)

    if len(vectors) != len(chunks):
        raise ValueError(
            "Embedding count does not match chunk count."
        )

    embedding_objects = [
        Embedding(
            chunk=chunk,
            embedding_vector=vector,
            model_name="intfloat/multilingual-e5-small",
        )
        for chunk, vector in zip(chunks, vectors)
    ]

    with transaction.atomic():
        Embedding.objects.bulk_create(
            embedding_objects,
            ignore_conflicts=True,
        )

        document = Document.objects.get(
            id=document_id
        )

        total_chunks = DocumentChunk.objects.filter(
            document_id=document_id
        ).count()

        total_embeddings = Embedding.objects.filter(
            chunk__document_id=document_id
        ).count()

        if (
            total_chunks > 0
            and total_embeddings == total_chunks
        ):
            document.status = "Indexed"
            document.save(update_fields=["status"])

    return {
        "document_id": document_id,
        "chunks_processed": len(chunks),
        "dimension": dimension,
        "status": document.status,
    }