import logging
from celery import shared_task
from django.db import transaction

from api.services import generate_embeddings

from .models import Document, DocumentChunk, Embedding
from .chunking import chunk_text
from .cleanup import purge_superseded_versions
from .extractors.pdf import extract_pdf_text
from .extractors.txt import extract_txt_text
from .extractors.word import extract_word_text
from .filetypes import (
    EMAIL_FILE_TYPES,
    IMAGE_FILE_TYPES,
    TABULAR_FILE_TYPES,
)
from .versioning import ARCHIVED_STATUS

logger = logging.getLogger(__name__)
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

        # The version may have been superseded between the upload and
        # this task running. Resurrecting it here would put an obsolete
        # procedure back into the index, so the task declines instead.
        if document.status == ARCHIVED_STATUS:
            logger.info(
                "Skipping processing for archived document %s.",
                document_id,
            )
            return {
                "document_id": document_id,
                "skipped": "archived",
            }

        document.status = "Processing"
        document.save(update_fields=["status"])

        chunks = None

        with document.file_path.open("rb") as file:
            if document.file_type == "application/pdf":
                # A scanned PDF has no text layer. The extractor keeps
                # the text of real pages and sends only image-only ones
                # to Tesseract, in the worker rather than the web proc.
                extracted_text = extract_pdf_text(file)

            elif document.file_type == "text/plain":
                extracted_text = extract_txt_text(file)

            elif document.file_type in (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
            ):
                extracted_text = extract_word_text(file)

            elif document.file_type in TABULAR_FILE_TYPES:
                # Imported here rather than at module scope: `views.py`
                # imports this module to enqueue the task, so a
                # top-level import would pull pandas into every web
                # process — a hundred megabytes and a noticeable slice
                # of boot time for a branch only the worker reaches.
                from .extractors.tabular import extract_tabular_rows

                # A table is chunked by row, not by token count: the
                # generic chunker cuts mid-row and drops the header, and
                # a passage of bare cells answers nothing.
                chunks = extract_tabular_rows(
                    file,
                    document.file_type,
                )

            elif document.file_type in EMAIL_FILE_TYPES:
                from .extractors.email import extract_email_chunks

                # An email is chunked by its own rules: the header block
                # is glued to the first passage and repeated on every
                # continuation, so a search for the sender or the
                # subject works wherever the chunk boundary landed.
                chunks = extract_email_chunks(file)

            elif document.file_type in IMAGE_FILE_TYPES:
                # No text can be selected from a photograph: this is
                # the only path that reaches OCR for an image upload.
                from .extractors.ocr import extract_image_text

                extracted_text = extract_image_text(file)

            else:
                raise ValueError(
                    f"Unsupported file type: {document.file_type}"
                )

        if chunks is None:
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
                logger.exception(
                     "Failed to update document %s status to Failed",
                     document.id,
              )

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
            # A tombstoned chunk belongs to a version that has already
            # been purged. Embedding it would pay for inference whose
            # only possible outcome is a vector we then delete.
            is_active=True,
        ).order_by("chunk_index")
    )

    if not chunks:
        return {
            "document_id": document_id,
            "count": 0,
        }

    # Check before paying for the embedding call: an archived version
    # must not consume inference, and must not get its vectors back.
    current_status = (
        Document.objects
        .filter(id=document_id)
        .values_list("status", flat=True)
        .first()
    )

    if current_status == ARCHIVED_STATUS:
        Embedding.objects.filter(chunk_id__in=chunk_ids).delete()

        logger.info(
            "Skipping embeddings for archived document %s.",
            document_id,
        )

        return {
            "document_id": document_id,
            "count": 0,
            "skipped": "archived",
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

        # Lock the row before deciding anything: the archiving side
        # takes the same lock, so one of the two orders always wins
        # cleanly. Without it, an archive that commits between the
        # insert and this read would leave vectors on an archived
        # document — invisible today, but one restore away from being
        # citable again.
        document = (
            Document.objects
            .select_for_update()
            .get(id=document_id)
        )

        if document.status == ARCHIVED_STATUS:
            Embedding.objects.filter(chunk_id__in=chunk_ids).delete()

            logger.info(
                "Document %s was archived during embedding; vectors dropped.",
                document_id,
            )

            return {
                "document_id": document_id,
                "chunks_processed": len(chunks),
                "dimension": dimension,
                "status": document.status,
                "skipped": "archived",
            }

        total_chunks = DocumentChunk.objects.filter(
            document_id=document_id,
            is_active=True,
        ).count()

        total_embeddings = Embedding.objects.filter(
            chunk__document_id=document_id,
        ).count()

        if (
            total_chunks > 0
            and total_embeddings == total_chunks
        ):
            document.status = "Indexed"
            document.save(update_fields=["status"])

            # Only now is the replacement usable, so only now is it
            # safe to erase what it replaced. `on_commit` keeps the
            # worker from picking up a row that is still "Processing"
            # and skipping the cleanup as a no-op.
            #
            # A first upload has nothing to retire, and skipping the
            # enqueue here keeps the queue free of one no-op task per
            # document the platform has ever seen.
            if document.parent_document_id is not None:
                transaction.on_commit(
                    lambda: cleanup_superseded_document.delay(
                        document_id
                    )
                )

    return {
        "document_id": document_id,
        "chunks_processed": len(chunks),
        "dimension": dimension,
        "status": document.status,
    }


@shared_task(
    name="documents.cleanup_superseded_document",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_kwargs={"max_retries": 5},
)
def cleanup_superseded_document(document_id: int):
    """
    Take every version that `document_id` replaced out of the index.

    Enqueued when a replacement finishes indexing, and only then: the
    old version must stay searchable for as long as the new one is not.
    A document that never reaches `Indexed` therefore never triggers a
    purge, which is the correct outcome — its predecessor is still the
    best answer available.

    The task is safe to run twice, out of order, or for a document that
    was deleted meanwhile. Celery can deliver the same message more than
    once; the purge is written so that the second delivery is a no-op.
    """

    document = (
        Document.objects
        .filter(pk=document_id)
        .first()
    )

    if document is None:
        logger.info(
            "Cleanup skipped: document %s no longer exists.",
            document_id,
        )

        return {"document_id": document_id, "skipped": "missing"}

    if document.status != "Indexed":
        # Either the replacement failed, or it was itself superseded
        # before this task ran. In both cases the newest version's own
        # cleanup will walk the chain and cover these rows.
        logger.info(
            "Cleanup skipped: document %s is %s, not Indexed.",
            document_id,
            document.status,
        )

        return {
            "document_id": document_id,
            "skipped": "not_indexed",
            "status": document.status,
        }

    summary = purge_superseded_versions(document)

    logger.info(
        "Cleanup for document %s: %s version(s), %s chunk(s), "
        "%s vector(s).",
        document_id,
        summary["versions_purged"],
        summary["chunks_tombstoned"],
        summary["embeddings_deleted"],
    )

    return summary