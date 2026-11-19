"""
Sub-task 3 — the routing decision and the OCR result.

A PDF is not "text" or "scan" as a whole: a scanned appendix behind a
typed cover page needs both paths in one document. These tests pin the
routing (never OCR a page that already has text), the page order, the
bounded batching, and the whole upload → chunk → keyword-search path.
No Tesseract binary is needed: the native boundary is mocked.

    ./venv/Scripts/python.exe -m pytest tests/test_ocr_extraction.py -q
"""

import io
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from api.services import keyword_search
from documents.extractors.ocr import (
    OCRPageLimitError,
    extract_image_text,
    ocr_pdf_pages,
)
from documents.extractors.pdf import (
    NoSelectableTextError,
    extract_pdf_text,
)
from documents.models import Document, DocumentChunk
from documents.tasks import generate_embedding_batch, process_document
from tests.factories import UserFactory


OCR_TEXT = "صورتجلسه شماره ۱۲۳ در تاریخ ۱۴۰۲ صادر شد."


def fake_embeddings(texts):
    return [[0.0] * 384 for _ in texts], 384


def fake_reader(texts):
    reader = MagicMock()
    reader.pages = []

    for text in texts:
        page = MagicMock()
        page.extract_text.return_value = text
        reader.pages.append(page)

    return reader


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (120, 60), color="white").save(buffer, format="PNG")

    return buffer.getvalue()


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


# -- PDF routing -------------------------------------------------------


def test_a_pdf_with_selectable_text_never_calls_ocr():
    with patch(
        "documents.extractors.pdf.PdfReader",
        return_value=fake_reader(["Typed letter with selectable text."]),
    ), patch("documents.extractors.pdf.ocr_pdf_pages") as recognize:
        text = extract_pdf_text(io.BytesIO(b"%PDF-1.7 fake"))

    assert text == "Typed letter with selectable text."
    recognize.assert_not_called()


def test_an_image_only_pdf_is_sent_to_ocr():
    with patch(
        "documents.extractors.pdf.PdfReader",
        return_value=fake_reader(["", "  \n "]),
    ), patch(
        "documents.extractors.pdf.ocr_pdf_pages",
        return_value={0: OCR_TEXT, 1: "صفحه دوم"},
    ) as recognize:
        text = extract_pdf_text(io.BytesIO(b"%PDF-1.7 fake"))

    recognize.assert_called_once_with(b"%PDF-1.7 fake", [0, 1])
    assert text == f"{OCR_TEXT}\n\nصفحه دوم"


def test_a_mixed_pdf_keeps_page_order_and_ocr_only_the_scans():
    with patch(
        "documents.extractors.pdf.PdfReader",
        return_value=fake_reader(
            [
                "Typed cover sheet with a readable text layer.",
                "",
                "Another typed page with a readable text layer.",
                "",
            ]
        ),
    ), patch(
        "documents.extractors.pdf.ocr_pdf_pages",
        return_value={1: "پیوست اول", 3: "پیوست دوم"},
    ) as recognize:
        text = extract_pdf_text(io.BytesIO(b"%PDF-1.7 fake"))

    recognize.assert_called_once_with(b"%PDF-1.7 fake", [1, 3])
    assert text == (
        "Typed cover sheet with a readable text layer.\n\n"
        "پیوست اول\n\n"
        "Another typed page with a readable text layer.\n\n"
        "پیوست دوم"
    )


def test_a_short_text_layer_is_not_mistaken_for_a_text_page():
    # Scanned letters often carry a one-word footer from the OCR that
    # produced them; below the threshold the page still needs OCR.
    with patch(
        "documents.extractors.pdf.PdfReader",
        return_value=fake_reader(["Page 1"]),
    ), patch(
        "documents.extractors.pdf.ocr_pdf_pages",
        return_value={0: OCR_TEXT},
    ) as recognize:
        text = extract_pdf_text(io.BytesIO(b"%PDF-1.7 fake"))

    recognize.assert_called_once()
    assert text == OCR_TEXT


def test_preview_mode_rejects_a_scan_instead_of_starting_tesseract():
    with patch(
        "documents.extractors.pdf.PdfReader",
        return_value=fake_reader([""]),
    ), patch("documents.extractors.pdf.ocr_pdf_pages") as recognize:
        with pytest.raises(NoSelectableTextError):
            extract_pdf_text(io.BytesIO(b"%PDF-1.7 fake"), allow_ocr=False)

    recognize.assert_not_called()


def test_a_scan_that_yields_nothing_fails_the_document():
    with patch(
        "documents.extractors.pdf.PdfReader",
        return_value=fake_reader([""]),
    ), patch("documents.extractors.pdf.ocr_pdf_pages", return_value={}):
        with pytest.raises(ValueError, match="No extractable text"):
            extract_pdf_text(io.BytesIO(b"%PDF-1.7 fake"))


# -- OCR page batching --------------------------------------------------


def test_contiguous_pages_are_converted_in_bounded_batches():
    images = [Image.new("L", (10, 10)) for _ in range(3)]

    with patch.object(ocr_module(), "require_tesseract"), patch(
        "pdf2image.convert_from_bytes", return_value=images
    ) as convert, patch(
        "documents.extractors.ocr.image_to_text",
        side_effect=["صفحه ۱", "صفحه ۲", "صفحه ۵"],
    ):
        result = ocr_pdf_pages(b"%PDF", [0, 1, 4])

    assert result == {0: "صفحه ۱", 1: "صفحه ۲", 4: "صفحه ۵"}
    assert [
        (call.kwargs["first_page"], call.kwargs["last_page"])
        for call in convert.call_args_list
    ] == [(1, 2), (5, 5)]
    assert all(call.kwargs["dpi"] == 150 for call in convert.call_args_list)


def test_the_page_budget_is_enforced_before_rasterising():
    with patch.object(ocr_module(), "require_tesseract"), patch(
        "pdf2image.convert_from_bytes"
    ) as convert:
        with pytest.raises(OCRPageLimitError, match="limit is 20"):
            ocr_pdf_pages(b"%PDF", list(range(21)))

    convert.assert_not_called()


def ocr_module():
    from documents.extractors import ocr

    return ocr


# -- image path ---------------------------------------------------------


def test_an_image_is_read_without_changing_the_upload():
    with patch(
        "documents.extractors.ocr.image_to_text", return_value=OCR_TEXT
    ) as recognize:
        text = extract_image_text(io.BytesIO(png_bytes()))

    assert text == OCR_TEXT
    image = recognize.call_args.args[0]
    assert image.size == (120, 60)


# -- upload → chunk → search -------------------------------------------


@pytest.mark.django_db
def test_an_uploaded_png_becomes_a_searchable_chunk():
    user = UserFactory()

    with patch("documents.views.process_document.delay"), patch(
        "documents.views.transaction.on_commit",
        side_effect=lambda callback: callback(),
    ):
        response = client_for(user).post(
            "/api/documents/",
            {
                "title": "صورتجلسه اسکن شده",
                "department": user.department_id,
                "file_path": SimpleUploadedFile(
                    "letter.png",
                    png_bytes(),
                    content_type="image/png",
                ),
            },
            format="multipart",
        )

    assert response.status_code == 201, response.data
    document = Document.objects.get(id=response.data["document_id"])
    assert document.file_type == "image/png"

    with patch(
        "documents.extractors.ocr.extract_image_text",
        return_value=OCR_TEXT,
    ), patch("documents.tasks.generate_embedding_batch.delay"):
        process_document.run(document.id)

    chunks = DocumentChunk.objects.filter(document=document)
    assert chunks.count() >= 1
    assert OCR_TEXT in chunks.first().content

    chunk_ids = list(chunks.values_list("id", flat=True))

    with patch(
        "documents.tasks.generate_embeddings", side_effect=fake_embeddings
    ):
        generate_embedding_batch.run(document.id, chunk_ids)

    assert Document.objects.get(id=document.id).status == "Indexed"
    assert {c.id for c in keyword_search("صورتجلسه", user=user)} == set(chunk_ids)


@pytest.mark.django_db
def test_the_preview_of_an_image_uses_stored_text_without_ocr():
    from documents.preview import extract_document_text

    user = UserFactory()
    document = Document.objects.create(
        title="scan",
        file_type="image/png",
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        file_path="documents/tenant_1/scan.png",
        status="Indexed",
    )
    document.file_path.save("scan.png", io.BytesIO(png_bytes()), save=True)
    DocumentChunk.objects.create(
        document=document,
        content=OCR_TEXT,
        chunk_index=0,
    )

    with patch(
        "documents.extractors.ocr.image_to_text", side_effect=AssertionError
    ):
        text, _ = extract_document_text(document)

    assert text == OCR_TEXT
