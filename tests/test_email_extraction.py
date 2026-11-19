"""
Sub-task 2 — an email becomes one passage that keeps its metadata.

The acceptance criteria for this feature are "upload a `.eml`" and "a
search for the sender or the subject returns the email". Both depend on
the same property: the headers and the body have to end up in the same
chunk, because the sender's name and the subject appear nowhere in the
body. These tests pin that, and the encoding cases that make real email
hard — base64, quoted-printable, HTML-only bodies, encoded-word subjects
and legacy charsets.
"""

import base64
import io
import quopri
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from api.services import keyword_search
from documents.extractors.email import (
    extract_email_chunks,
    extract_email_text,
    looks_like_email,
)
from documents.filetypes import EMAIL_MIME
from documents.models import Document, DocumentChunk
from documents.tasks import generate_embedding_batch, process_document
from tests.factories import UserFactory


SUBJECT = "صورت‌حساب سالیانه"
SENDER = "سارا احمدی <sara@example.com>"
BODY = "سلام. مبلغ صورت‌حساب سالیانه پرداخت شد."


def encoded_word(value):
    return f"=?UTF-8?B?{base64.b64encode(value.encode('utf-8')).decode()}?="


def eml_bytes(
    body=BODY,
    *,
    subject=SUBJECT,
    sender=SENDER,
    to="team@example.com",
    date="Mon, 4 Mar 2024 10:22:00 +0330",
    charset="utf-8",
    transfer_encoding="8bit",
    content_type="text/plain",
    extra_headers=(),
    raw_subject=None,
):
    payload = body.encode(charset)

    if transfer_encoding == "base64":
        encoded = base64.encodebytes(payload)
    elif transfer_encoding == "quoted-printable":
        encoded = quopri.encodestring(payload)
    else:
        encoded = payload

    headers = [
        f"From: {sender}",
        f"To: {to}",
        f"Subject: {raw_subject if raw_subject is not None else subject}",
        f"Date: {date}",
        "MIME-Version: 1.0",
        f"Content-Type: {content_type}; charset={charset}",
        f"Content-Transfer-Encoding: {transfer_encoding}",
        *extra_headers,
    ]

    # The header block is UTF-8 (raw 8-bit headers are the realistic
    # case), while the body must be in the charset it declares — writing
    # both as UTF-8 would make the charset test prove nothing.
    return ("\n".join(headers) + "\n\n").encode("utf-8") + encoded + b"\n"


def chunks_for(data):
    return extract_email_chunks(io.BytesIO(data))


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def fake_embeddings(texts):
    return [[0.0] * 384 for _ in texts], 384


# -- the shape of a passage -------------------------------------------


def test_the_metadata_and_the_body_become_one_passage():
    chunks = chunks_for(eml_bytes())

    assert len(chunks) == 1

    passage = chunks[0]

    # The acceptance criteria, in one assertion: sender and subject are
    # in the same string as the body.
    assert "From: سارا احمدی <sara@example.com>" in passage
    assert "Subject: صورت‌حساب سالیانه" in passage
    assert "مبلغ صورت‌حساب سالیانه پرداخت شد." in passage


def test_the_date_is_normalised_to_iso():
    chunks = chunks_for(eml_bytes())

    # The raw header is RFC 5322 (`Mon, 4 Mar 2024 10:22:00 +0330`),
    # which embeds badly and reads badly. ISO keeps the offset.
    assert "Date: 2024-03-04T10:22+03:30" in chunks[0]


def test_the_recipient_is_kept():
    chunks = chunks_for(eml_bytes())

    assert "To: team@example.com" in chunks[0]


def test_an_email_without_a_body_is_rejected():
    # Headers only: no blank line, no body.
    data = (
        "From: a@b.com\nTo: c@d.com\nSubject: Empty\n"
        "Date: Mon, 4 Mar 2024 10:22:00 +0330\n\n"
    ).encode()

    with pytest.raises(ValueError, match="no readable text body"):
        chunks_for(data)


# -- encodings that real mail actually uses ---------------------------


def test_an_encoded_word_subject_is_decoded():
    """
    A Persian subject travels as `=?UTF-8?B?...?=`. Showing it verbatim
    would make the subject — the thing the user searches for — garbage.
    """

    chunks = chunks_for(eml_bytes(raw_subject=encoded_word(SUBJECT)))

    assert f"Subject: {SUBJECT}" in chunks[0]
    assert "=?UTF-8?B?" not in chunks[0]


def test_an_encoded_word_sender_name_is_decoded():
    chunks = chunks_for(
        eml_bytes(sender=f"{encoded_word('سارا احمدی')} <sara@example.com>")
    )

    assert "From: سارا احمدی <sara@example.com>" in chunks[0]


def test_a_base64_body_is_decoded():
    chunks = chunks_for(eml_bytes(transfer_encoding="base64"))

    assert "مبلغ صورت‌حساب سالیانه پرداخت شد." in chunks[0]


def test_a_quoted_printable_body_is_decoded():
    chunks = chunks_for(eml_bytes(transfer_encoding="quoted-printable"))

    assert "مبلغ صورت‌حساب سالیانه پرداخت شد." in chunks[0]


def test_a_windows_1256_body_is_decoded():
    """
    Corporate mail from an older Persian Outlook is cp1256, not UTF-8,
    and it says so in its own Content-Type. Reading it as UTF-8 would
    produce a body of replacement characters that matches nothing.
    """

    # No ZWNJ here: cp1256 has no code point for it, and a test that
    # cannot be encoded proves nothing about decoding.
    body = "سلام. مبلغ صورت حساب پرداخت شد."

    chunks = chunks_for(eml_bytes(charset="cp1256", body=body))

    assert body in chunks[0]


def test_an_html_only_email_is_converted_to_text():
    markup = (
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>سلام.</p><p>مبلغ صورت‌حساب <b>پرداخت</b> شد.</p>"
        "<script>alert('x')</script></body></html>"
    )

    chunks = chunks_for(eml_bytes(markup, content_type="text/html"))

    assert "مبلغ صورت‌حساب پرداخت شد." in chunks[0]
    # Markup and scripts are not content.
    assert "<p>" not in chunks[0]
    assert "alert" not in chunks[0]
    assert "color:red" not in chunks[0]


def test_plain_text_wins_when_both_parts_exist():
    """
    A multipart/alternative message carries the same text twice, once as
    plain and once as HTML. Indexing both would double every sentence and
    halve the effective similarity of each.
    """

    data = (
        "From: a@b.com\n"
        "To: c@d.com\n"
        "Subject: Both\n"
        "Date: Mon, 4 Mar 2024 10:22:00 +0330\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/alternative; boundary="BOUND"\n'
        "\n"
        "--BOUND\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "the plain version\n"
        "--BOUND\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<p>the html version</p>\n"
        "--BOUND--\n"
    ).encode()

    chunks = chunks_for(data)

    assert "the plain version" in chunks[0]
    assert "the html version" not in chunks[0]


def test_an_attachment_is_named_but_not_indexed():
    data = (
        "From: a@b.com\n"
        "To: c@d.com\n"
        "Subject: With attachment\n"
        "Date: Mon, 4 Mar 2024 10:22:00 +0330\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="BOUND"\n'
        "\n"
        "--BOUND\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "please find the report attached\n"
        "--BOUND\n"
        "Content-Type: application/pdf\n"
        'Content-Disposition: attachment; filename="report.pdf"\n'
        "Content-Transfer-Encoding: base64\n"
        "\n"
        "JVBERi0xLjQK\n"
        "--BOUND--\n"
    ).encode()

    passage = chunks_for(data)[0]

    # The filename is metadata worth searching for...
    assert "Attachments: report.pdf" in passage
    # ...but the base64 of a PDF is noise in an embedding.
    assert "JVBERi0xLjQK" not in passage


# -- length ------------------------------------------------------------


def test_a_long_email_is_split_and_every_chunk_keeps_the_subject():
    """
    The embedding model truncates around 512 tokens, so a long email has
    to be split or its second half is unsearchable. Splitting naively
    would separate the subject from everything after the first chunk,
    which breaks the acceptance criteria for exactly the emails that
    matter most — the long ones.
    """

    body = " ".join(f"line {index} of a long email body" for index in range(400))

    chunks = chunks_for(eml_bytes(body))

    assert len(chunks) > 1
    assert chunks[0].startswith("Subject: صورت‌حساب سالیانه")

    for passage in chunks[1:]:
        assert passage.startswith("Subject: صورت‌حساب سالیانه")
        assert "From: سارا احمدی <sara@example.com>" in passage


def test_the_preview_is_the_indexed_text():
    data = eml_bytes()

    assert extract_email_text(io.BytesIO(data)) == "\n\n".join(chunks_for(data))


# -- the header-block check used at upload ----------------------------


def test_a_text_file_does_not_look_like_an_email():
    assert looks_like_email(io.BytesIO(b"just some notes\nnothing here\n")) is False


def test_an_email_looks_like_an_email():
    assert looks_like_email(io.BytesIO(eml_bytes())) is True


def test_a_body_that_mentions_a_header_is_not_an_email():
    """
    The check only reads the header block, up to the first blank line. A
    plain text file whose *body* happens to contain `From:` is not an
    email, and treating it as one would index a stray colon as metadata.
    """

    data = b"Meeting notes\n\nFrom: someone\nSubject: not really\n"

    assert looks_like_email(io.BytesIO(data)) is False


# -- end to end --------------------------------------------------------


def upload_email(user, data, filename="invoice.eml"):
    with patch(
        "documents.views.process_document.delay",
    ), patch(
        "documents.views.transaction.on_commit",
        side_effect=lambda callback: callback(),
    ):
        return client_for(user).post(
            "/api/documents/",
            {
                "title": "Annual invoice",
                "department": user.department_id,
                "file_path": SimpleUploadedFile(
                    filename,
                    data,
                    content_type=EMAIL_MIME,
                ),
            },
            format="multipart",
        )


def index(user, data):
    response = upload_email(user, data)

    assert response.status_code == 201

    document_id = response.data["document_id"]

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
    assert document.file_type == EMAIL_MIME

    return document


@pytest.mark.django_db
def test_an_uploaded_email_reaches_indexed():
    user = UserFactory()

    document = index(user, eml_bytes())

    assert DocumentChunk.objects.filter(document=document).count() == 1


@pytest.mark.django_db
def test_searching_the_sender_finds_the_email():
    user = UserFactory()

    index(user, eml_bytes())

    results = list(keyword_search("سارا احمدی", user=user))

    assert len(results) == 1
    assert "مبلغ صورت‌حساب" in results[0].content


@pytest.mark.django_db
def test_searching_the_subject_finds_the_email():
    user = UserFactory()

    index(user, eml_bytes())

    results = list(keyword_search("صورت‌حساب سالیانه", user=user))

    assert len(results) == 1
    assert "sara@example.com" in results[0].content


@pytest.mark.django_db
def test_a_search_for_something_absent_still_returns_nothing():
    user = UserFactory()

    index(user, eml_bytes())

    assert list(keyword_search("قرارداد اجاره", user=user)) == []
