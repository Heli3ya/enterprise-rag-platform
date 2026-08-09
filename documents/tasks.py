from celery import shared_task
from django.db import transaction
from .models import Document, DocumentChunk
from .chunking import chunk_text
from .extractors.pdf import extract_pdf_text
from .extractors.txt import extract_txt_text
from .extractors.word import extract_word_text
@shared_task
def process_document(document_id: int):
    """
    Extract, chunk, and store a document asynchronously using Celery.
    """
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
        DocumentChunk.objects.filter(document=document).delete()
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
            document.status = "Chunked"
            document.save(update_fields=["status"])
        return {
            "document_id": document.id,
            "chunks_created": len(chunk_objects),
            "status": document.status,
        }
    except Exception:
        try:
            document.status = "Failed"
            document.save(update_fields=["status"])
        except Exception:
            pass
        raise