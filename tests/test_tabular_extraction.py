"""
Sub-task 3 — a row becomes a passage, and the passage is the row.

The acceptance criterion is precise: searching for a word that sits in
one cell must retrieve *that row* as text. Not a window around it, not a
block of forty rows, and not `| 120 | USD |` with no column names to
say what the 120 measures.

The first test is that sentence, run end to end through the real upload,
the real extractor and the real keyword search.
"""

import io
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from api.services import keyword_search
from documents.extractors import tabular
from documents.extractors.tabular import extract_tabular_rows
from documents.filetypes import CSV_MIME, XLSX_MIME
from documents.models import Document, DocumentChunk
from documents.tasks import (
    generate_embedding_batch,
    process_document,
)
from tests.factories import UserFactory


def workbook_bytes(rows, title="Prices"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title

    for row in rows:
        sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


def extract(rows, title="Prices"):
    return extract_tabular_rows(
        io.BytesIO(workbook_bytes(rows, title)),
        XLSX_MIME,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def fake_embeddings(texts):
    return [[0.0] * 384 for _ in texts], 384


@pytest.mark.django_db
def test_each_row_becomes_its_own_chunk():
    rows = extract(
        [
            ["Product", "Price"],
            ["Widget A", 120],
            ["Widget B", 80],
        ]
    )

    assert len(rows) == 2
    assert "Widget A" in rows[0]
    assert "Widget B" in rows[1]
    # Neither row carries the other: a chunk that answers a price
    # question must not also answer a different one.
    assert "Widget B" not in rows[0]


@pytest.mark.django_db
def test_every_chunk_repeats_the_column_names():
    rows = extract(
        [
            ["Product", "Price", "Unit"],
            ["Widget A", 120, "USD"],
        ]
    )

    assert "| Product | Price | Unit |" in rows[0]
    assert "| Widget A | 120 | USD |" in rows[0]
    assert rows[0].startswith("Sheet: Prices")


@pytest.mark.django_db
def test_numbers_keep_their_human_form():
    rows = extract(
        [
            ["Product", "Price"],
            ["Widget A", 120],
        ]
    )

    # A spreadsheet stores 120 as a float. `120.0` in a passage that is
    # meant to be quotable is wrong.
    assert "| Widget A | 120 |" in rows[0]
    assert "120.0" not in rows[0]


@pytest.mark.django_db
def test_a_sheet_without_a_header_keeps_its_first_row():
    rows = extract(
        [
            [1, 2],
            [3, 4],
        ]
    )

    # All-numeric first row: treating it as a header would silently drop
    # a record from a price list exported without labels.
    assert len(rows) == 2
    assert "Column 1" in rows[0]
    assert "| 1 | 2 |" in rows[0]


@pytest.mark.django_db
def test_empty_rows_are_skipped():
    rows = extract(
        [
            ["Product", "Price"],
            [None, None],
            ["Widget A", 120],
        ]
    )

    assert len(rows) == 1


@pytest.mark.django_db
def test_duplicate_column_names_are_disambiguated():
    rows = extract(
        [
            ["Price", "Price"],
            [120, 80],
        ]
    )

    assert "| Price | Price (2) |" in rows[0]


@pytest.mark.django_db
def test_a_wide_sheet_is_cut_at_the_readable_width():
    header = [f"Column {index}" for index in range(60)]
    values = list(range(60))

    rows = extract([header, values])

    assert "Column 45" not in rows[0]


@pytest.mark.django_db
def test_the_row_cap_is_respected(monkeypatch):
    monkeypatch.setattr(tabular, "MAX_ROWS", 2)

    rows = extract(
        [
            ["Product", "Price"],
            ["A", 1],
            ["B", 2],
            ["C", 3],
        ]
    )

    assert len(rows) == 2


@pytest.mark.django_db
def test_a_long_cell_is_truncated_not_dropped():
    rows = extract(
        [
            ["Note"],
            ["x" * 5000],
        ]
    )

    assert len(rows) == 1
    assert len(rows[0]) <= tabular.MAX_ROW_CHARS


@pytest.mark.django_db
def test_a_semicolon_csv_is_split_into_columns():
    rows = extract_tabular_rows(
        io.BytesIO("Product;Price\nWidget A;120\n".encode()),
        CSV_MIME,
    )

    assert "| Product | Price |" in rows[0]
    assert "| Widget A | 120 |" in rows[0]


@pytest.mark.django_db
def test_leading_zeros_survive_in_a_csv():
    rows = extract_tabular_rows(
        io.BytesIO(b"Name,Phone\nAli,09123456789\n"),
        CSV_MIME,
    )

    # Read as a number, this becomes 9123456789 — a different phone
    # number.
    assert "09123456789" in rows[0]


@pytest.mark.django_db
def test_searching_a_cell_returns_exactly_that_row():
    user = UserFactory()

    with patch(
        "documents.views.process_document.delay",
    ), patch(
        "documents.views.transaction.on_commit",
        side_effect=lambda callback: callback(),
    ):
        upload = client_for(user).post(
            "/api/documents/",
            {
                "title": "prices",
                "department": user.department_id,
                "file_path": SimpleUploadedFile(
                    "prices.xlsx",
                    workbook_bytes(
                        [
                            ["Product", "Price", "Unit"],
                            ["Widget A", 120, "USD"],
                            ["Widget B", 80, "USD"],
                            ["Widget C", 45, "EUR"],
                        ]
                    ),
                    content_type=XLSX_MIME,
                ),
            },
            format="multipart",
        )

    assert upload.status_code == 201

    document_id = upload.data["document_id"]

    with patch("documents.tasks.generate_embedding_batch.delay"):
        process_document.run(document_id)

    assert DocumentChunk.objects.filter(
        document_id=document_id
    ).count() == 3

    # "EUR" is in one cell of one row. "widget" would match all three,
    # because every row repeats the product prefix — which is the point
    # of the test: the retrieval unit is the row, so a word that lives
    # in one cell must come back as one passage, not as the table.
    results = list(keyword_search("EUR", user=user))

    # One row, not three, and the row arrives with its header.
    assert len(results) == 1
    assert "Widget C" in results[0].content
    assert "| Product | Price | Unit |" in results[0].content
    assert "Widget A" not in results[0].content


@pytest.mark.django_db
def test_an_uploaded_spreadsheet_reaches_indexed():
    user = UserFactory()

    with patch(
        "documents.views.process_document.delay",
    ), patch(
        "documents.views.transaction.on_commit",
        side_effect=lambda callback: callback(),
    ):
        upload = client_for(user).post(
            "/api/documents/",
            {
                "title": "staff",
                "department": user.department_id,
                "file_path": SimpleUploadedFile(
                    "staff.xlsx",
                    workbook_bytes(
                        [
                            ["Name", "Team", "Salary"],
                            ["Sara", "Platform", 4200],
                        ]
                    ),
                    content_type=XLSX_MIME,
                ),
            },
            format="multipart",
        )

    document_id = upload.data["document_id"]

    with patch("documents.tasks.generate_embedding_batch.delay"):
        process_document.run(document_id)

    chunk_ids = list(
        DocumentChunk.objects
        .filter(document_id=document_id)
        .values_list("id", flat=True)
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ):
        generate_embedding_batch.run(document_id, chunk_ids)

    document = Document.objects.get(id=document_id)

    assert document.status == "Indexed"
    assert document.file_type == XLSX_MIME


@pytest.mark.django_db
def test_an_uploaded_csv_reaches_indexed():
    """
    The same journey for a CSV, through Django's storage handle rather
    than a `BytesIO`.

    This is not a duplicate of the xlsx case. The extractor used to hand
    the storage handle straight to `pandas.read_csv`, which works with a
    `BytesIO` and raises `TypeError: a bytes-like object is required`
    with a Django `File` — so the upload was accepted, the document went
    to `Failed` in the worker, and every test still passed because they
    all used an in-memory buffer.
    """

    user = UserFactory()

    with patch(
        "documents.views.process_document.delay",
    ), patch(
        "documents.views.transaction.on_commit",
        side_effect=lambda callback: callback(),
    ):
        upload = client_for(user).post(
            "/api/documents/",
            {
                "title": "prices",
                "department": user.department_id,
                "file_path": SimpleUploadedFile(
                    "prices.csv",
                    "کالا,قیمت,واحد\nبلبرینگ,45,یورو\nواشر,30,یورو\n".encode(),
                    content_type=CSV_MIME,
                ),
            },
            format="multipart",
        )

    assert upload.status_code == 201

    document_id = upload.data["document_id"]

    with patch("documents.tasks.generate_embedding_batch.delay"):
        process_document.run(document_id)

    chunk_ids = list(
        DocumentChunk.objects
        .filter(document_id=document_id)
        .values_list("id", flat=True)
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ):
        generate_embedding_batch.run(document_id, chunk_ids)

    document = Document.objects.get(id=document_id)

    assert document.status == "Indexed"
    assert document.file_type == CSV_MIME

    contents = list(
        DocumentChunk.objects
        .filter(document_id=document_id)
        .order_by("chunk_index")
        .values_list("content", flat=True)
    )

    assert len(contents) == 2
    assert "| کالا | قیمت | واحد |" in contents[0]
    assert "بلبرینگ" in contents[0]

    results = list(keyword_search("بلبرینگ", user=user))

    assert len(results) == 1
    assert "45" in results[0].content
    assert "واشر" not in results[0].content
