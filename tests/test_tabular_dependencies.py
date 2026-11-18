"""
Sub-task 1 — the tabular libraries are present where the work happens.

The extractor runs in the Celery worker, not in the web process, so
"pandas is installed" is not a fact about `requirements.txt`; it is a
fact about whether the worker can import the module and read a file. A
missing dependency there fails long after the upload, as an opaque
`Failed` document.

These tests therefore read a real workbook through the real extractor in
the process that runs the task.
"""

import io

import pytest
from openpyxl import Workbook

from documents.extractors.tabular import extract_tabular_rows
from documents.filetypes import CSV_MIME, XLSX_MIME


def workbook_bytes(rows, sheet_title="Prices"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title

    for row in rows:
        sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


@pytest.mark.django_db
def test_pandas_is_importable_where_the_task_runs():
    import pandas

    assert pandas.__version__


@pytest.mark.django_db
def test_openpyxl_is_importable_where_the_task_runs():
    import openpyxl

    assert openpyxl.__version__


@pytest.mark.django_db
def test_the_task_module_can_load_the_tabular_extractor():
    """
    The worker imports the extractor lazily, inside the branch that
    handles a spreadsheet. This test performs exactly that import in the
    interpreter the task runs in, so a library missing from the image
    fails here instead of in the middle of a user's upload.
    """

    import importlib

    module = importlib.import_module("documents.extractors.tabular")

    assert callable(module.extract_tabular_rows)


@pytest.mark.django_db
def test_importing_the_task_module_does_not_load_pandas():
    """
    `views.py` imports the task module to enqueue work, so an eager
    import would put pandas in every web process. The worker pays that
    cost on the first spreadsheet it sees; the request path never does.
    """

    import subprocess
    import sys

    probe = (
        "import django, os;"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings');"
        "django.setup();"
        "import documents.tasks, sys;"
        "print('pandas' in sys.modules)"
    )

    output = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert output.returncode == 0, output.stderr[-800:]
    assert output.stdout.strip().endswith("False")


@pytest.mark.django_db
def test_a_workbook_can_be_read_end_to_end():
    data = workbook_bytes(
        [
            ["Product", "Price"],
            ["Widget A", 120],
        ]
    )

    rows = extract_tabular_rows(io.BytesIO(data), XLSX_MIME)

    assert len(rows) == 1
    assert "Widget A" in rows[0]


@pytest.mark.django_db
def test_a_csv_can_be_read_end_to_end():
    rows = extract_tabular_rows(
        io.BytesIO(b"Product,Price\nWidget A,120\n"),
        CSV_MIME,
    )

    assert len(rows) == 1
    assert "Widget A" in rows[0]
