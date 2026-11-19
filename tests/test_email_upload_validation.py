"""
The upload gate accepts `.eml`, and only real `.eml`.

libmagic answers `message/rfc822` for a normal email but `text/plain`
when the headers are sparse — the same answer a `.txt` file gets. So the
extension alone is not enough, and neither is the MIME: what decides is
whether the bytes actually open with an RFC 822 header block.
"""

import base64

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from documents.filetypes import EMAIL_MIME
from tests.factories import DocumentFactory, UserFactory


def email_bytes(subject="Annual invoice", body="Please pay the invoice."):
    return (
        "From: Sara Ahmadi <sara@example.com>\n"
        "To: team@example.com\n"
        f"Subject: {subject}\n"
        "Date: Mon, 4 Mar 2024 10:22:00 +0330\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        f"{body}\n"
    ).encode("utf-8")


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
def test_an_eml_upload_is_accepted():
    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "invoice.eml",
        email_bytes(),
        EMAIL_MIME,
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_an_eml_upload_is_stored_as_an_email():
    """
    The stored type is what the worker dispatches on, so it has to be
    the email type and not `text/plain`.
    """

    from documents.models import Document

    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "invoice.eml",
        email_bytes(),
        "application/octet-stream",
    )

    assert response.status_code == 201
    assert Document.objects.get(id=response.data["document_id"]).file_type == EMAIL_MIME


@pytest.mark.django_db
def test_a_text_file_renamed_to_eml_is_rejected():
    """
    Without the header check this file is accepted — libmagic says
    `text/plain`, which is an allowed type — and then fails in Celery as
    an opaque `Failed` row the user cannot act on.
    """

    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "notes.eml",
        b"Just some meeting notes.\nNothing resembling a message here.\n",
        "text/plain",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_an_image_renamed_to_eml_is_rejected():
    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "photo.eml",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        "image/png",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_an_executable_renamed_to_eml_is_rejected():
    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "setup.eml",
        b"MZ\x90\x00" + b"\x00" * 64,
        "application/x-msdownload",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_an_email_with_only_a_subject_header_is_accepted():
    """
    A minimal message is still a message. The check asks for one
    recognised header, not for a well-formed one.
    """

    user = UserFactory()

    response = upload(
        client_for(user),
        user,
        "minimal.eml",
        b"Subject: Only a subject\n\nbody text\n",
        "text/plain",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_an_eml_with_a_base64_body_is_accepted():
    """
    Base64 is the default encoding for non-ASCII mail. The gate must not
    try to read the body as text — it is not text.
    """

    payload = base64.b64encode("مبلغ صورت‌حساب پرداخت شد.".encode("utf-8")).decode()

    data = (
        "From: Sara <sara@example.com>\n"
        "To: team@example.com\n"
        "Subject: Invoice\n"
        "Date: Mon, 4 Mar 2024 10:22:00 +0330\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "Content-Transfer-Encoding: base64\n"
        "\n"
        f"{payload}\n"
    ).encode()

    user = UserFactory()

    response = upload(client_for(user), user, "encoded.eml", data, EMAIL_MIME)

    assert response.status_code == 201


@pytest.mark.django_db
def test_a_new_version_of_an_email_is_accepted():
    user = UserFactory()
    document = DocumentFactory(uploaded_by=user, department=user.department)

    client = client_for(user)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(
            "documents.views.transaction.on_commit",
            lambda callback: callback(),
        )
        patcher.setattr("documents.views.process_document.delay", lambda *a, **k: None)

        response = client.post(
            f"/api/documents/{document.id}/versions/",
            {
                "file_path": SimpleUploadedFile(
                    "invoice-v2.eml",
                    email_bytes(subject="Annual invoice (revised)"),
                    content_type=EMAIL_MIME,
                ),
            },
            format="multipart",
        )

    assert response.status_code == 201
