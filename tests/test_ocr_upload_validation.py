"""
Upload-side acceptance for OCR files.

The bytes decide, not the extension: a `.png` that is actually a text
file must be rejected before Celery tries to decode it, and a real
JPEG must be stored as `image/jpeg` so the worker takes the OCR branch.
Running these tests requires no Tesseract binary — only the image
codecs in Pillow.

    ./venv/Scripts/python.exe -m pytest tests/test_ocr_upload_validation.py -q
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from documents.filetypes import JPEG_MIME, PNG_MIME
from documents.models import Document
from tests.factories import UserFactory


def image_bytes(fmt="PNG"):
    buffer = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (40, 20), color="white").save(buffer, format=fmt)

    return buffer.getvalue()


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def upload(user, filename, content, content_type):
    return client_for(user).post(
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
@pytest.mark.parametrize(
    ("filename", "fmt", "expected"),
    [
        ("letter.png", "PNG", PNG_MIME),
        ("letter.jpg", "JPEG", JPEG_MIME),
        ("letter.jpeg", "JPEG", JPEG_MIME),
    ],
)
def test_images_are_accepted_and_stored_with_the_detected_type(
    filename,
    fmt,
    expected,
):
    user = UserFactory()

    response = upload(user, filename, image_bytes(fmt), "application/octet-stream")

    assert response.status_code == 201, response.data
    assert Document.objects.get(id=response.data["document_id"]).file_type == expected


@pytest.mark.django_db
def test_a_text_file_renamed_to_png_is_rejected():
    user = UserFactory()

    response = upload(
        user,
        "letter.png",
        b"NOT A PNG, just Persian text in a file.\n",
        "image/png",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_a_png_renamed_to_jpg_is_rejected():
    user = UserFactory()

    response = upload(user, "letter.jpg", image_bytes("PNG"), JPEG_MIME)

    assert response.status_code == 400


@pytest.mark.django_db
def test_other_image_formats_are_still_rejected():
    user = UserFactory()

    response = upload(user, "letter.gif", b"GIF89a" + b"\x00" * 32, "image/gif")

    assert response.status_code == 400
