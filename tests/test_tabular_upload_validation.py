"""
Sub-task 2 — the upload gate accepts tables, and only tables.

The hard part is not adding two strings to a set. libmagic reports
`application/zip` for every `.xlsx` and `text/plain` for every `.csv`,
so an extension alone would let a renamed archive through, and a MIME
alone would reject every real spreadsheet. These tests pin both halves:
the formats that must be accepted, and the look-alikes that must not.
"""

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from documents.filetypes import CSV_MIME, XLSX_MIME
from tests.factories import DocumentFactory, UserFactory


def workbook_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active

    for row in rows:
        sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


def price_workbook():
    return workbook_bytes(
        [
            ["Product", "Price", "Unit"],
            ["Widget A", 120, "USD"],
        ]
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def upload(client, user, filename, content, content_type):
    return client.post(
        "/api/documents/",
        {
            "title": filename,
            "department": user.department_id,
            "file_path": SimpleUploadedFile(
                filename,
                content,
                content_type=content_type,
            ),
        },
        format="multipart",
    )


@pytest.mark.django_db
def test_an_xlsx_upload_is_accepted():
    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "prices.xlsx",
        price_workbook(),
        XLSX_MIME,
    )

    assert response.status_code == 201

    from documents.models import Document

    document = Document.objects.get(id=response.data["document_id"])

    # libmagic says `application/zip` for this file. What is stored has
    # to be the type the extractor dispatches on, not the container.
    assert document.file_type == XLSX_MIME


@pytest.mark.django_db
def test_a_csv_upload_is_accepted():
    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "prices.csv",
        b"Product,Price\nWidget A,120\n",
        "text/csv",
    )

    assert response.status_code == 201

    from documents.models import Document

    document = Document.objects.get(id=response.data["document_id"])

    assert document.file_type == CSV_MIME


@pytest.mark.django_db
def test_a_renamed_zip_is_rejected():
    user = UserFactory()
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "not a workbook")

    response = upload(
        client_for(user),
        user,
        "prices.xlsx",
        buffer.getvalue(),
        XLSX_MIME,
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_a_csv_that_is_not_utf8_is_rejected():
    user = UserFactory()

    # Windows-1256 bytes: readable by a spreadsheet, not by us, and the
    # user should learn that at upload time rather than from a Failed
    # row twenty seconds later. The text uses Arabic yeh (U+064A) and
    # ASCII digits because cp1256 has no code point for Persian yeh
    # (U+06CC) — encoding the Persian spelling here would fail in the
    # test itself, not in the code under test.
    response = upload(
        client_for(user),
        user,
        "prices.csv",
        "قيمت,كلا\n120,ويجت\n".encode("cp1256"),
        "text/csv",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_an_image_named_csv_is_rejected():
    user = UserFactory()

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    )

    response = upload(
        client_for(user),
        user,
        "prices.csv",
        png,
        "text/csv",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_an_executable_is_still_rejected():
    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "prices.exe",
        b"MZ\x90\x00" + b"\x00" * 200,
        "application/octet-stream",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_a_text_file_is_still_accepted():
    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "policy.txt",
        b"Receipts must be submitted within 30 days.",
        "text/plain",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_a_spreadsheet_can_be_uploaded_as_a_new_version():
    user = UserFactory()
    original = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title="Prices",
        status="Indexed",
    )

    response = client_for(user).post(
        f"/api/documents/{original.id}/versions/",
        {
            "file_path": SimpleUploadedFile(
                "prices-v2.xlsx",
                price_workbook(),
                content_type=XLSX_MIME,
            )
        },
        format="multipart",
    )

    assert response.status_code == 201

    from documents.models import Document

    replacement = Document.objects.get(id=response.data["document_id"])

    assert replacement.file_type == XLSX_MIME
    assert replacement.version == 2
