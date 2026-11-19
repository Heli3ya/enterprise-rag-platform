"""
What a file *is*, as opposed to what it is called.

libmagic reads the bytes, which is the right instinct: an extension is
supplied by the user and costs nothing to lie about. Three of the formats
this platform accepts defeat it anyway.

* `.xlsx` is a zip archive. libmagic answers `application/zip`, which is
  true and useless — every zip file gets the same answer.
* `.csv` is plain text. libmagic answers `text/plain`, exactly what it
  answers for a `.txt` file, so the two cannot be told apart.
* `.eml` usually reports `message/rfc822`, but falls back to
  `text/plain` when the headers are sparse — the same answer a `.txt`
  file gets.

JPEG and PNG, by contrast, are recognised from their magic bytes
reliably. They are still mapped from the extension, so a renamed file
is rejected at upload rather than indexed as a different format.

For those three the extension decides, but never on its own: it is
trusted only when the bytes agree with it. A `.xlsx` that is not a
spreadsheet, a `.csv` that is not decodable text, or an `.eml` with no
RFC 822 header block is still rejected at upload instead of failing
later in a background worker.
"""

import codecs
import zipfile
from pathlib import Path

import magic


XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument."
    "spreadsheetml.sheet"
)

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document"
)

CSV_MIME = "text/csv"

EMAIL_MIME = "message/rfc822"

JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"


# A photograph has no text layer at all; these go straight to OCR.
IMAGE_FILE_TYPES = {JPEG_MIME, PNG_MIME}


# Returned by `effective_file_type` when the extension promises one
# format and the bytes deliver another. It is deliberately not a real
# MIME type and never appears in `ALLOWED_FILE_TYPES`, so validation
# rejects the upload instead of storing a file the worker will fail on.
# Falling back to the raw MIME was the earlier behaviour and it was
# wrong: a Windows-1256 `.csv` reports `text/plain`, which is allowed,
# so the file was accepted and only failed later, in Celery.
INVALID_FILE_TYPE = "application/x-invalid-upload"


# The formats that carry a table rather than prose. They skip the
# token-based chunker and are chunked by row instead — see
# `documents/extractors/tabular.py`.
TABULAR_FILE_TYPES = {XLSX_MIME, CSV_MIME}


# An email carries its own metadata, and the extractor has to see the
# headers before it can decide what the body is, so it gets its own
# branch rather than being treated as plain text.
EMAIL_FILE_TYPES = {EMAIL_MIME}


ALLOWED_FILE_TYPES = {
    "application/pdf",
    "text/plain",
    "application/msword",
    DOCX_MIME,
    XLSX_MIME,
    CSV_MIME,
    EMAIL_MIME,
    JPEG_MIME,
    PNG_MIME,
}


# The type to record when the extension and the bytes agree.
EXTENSION_FILE_TYPES = {
    ".xlsx": XLSX_MIME,
    ".csv": CSV_MIME,
    ".docx": DOCX_MIME,
    ".eml": EMAIL_MIME,
    ".jpg": JPEG_MIME,
    ".jpeg": JPEG_MIME,
    ".png": PNG_MIME,
}


# What libmagic is allowed to answer for each extension. `text/plain` is
# here for CSV because that is what libmagic says; `application/zip` and
# `application/octet-stream` for the same reason on the OOXML side.
# `application/octet-stream` is also what a Windows client often sends,
# and it is only accepted together with an extension whose content is
# then verified.
ACCEPTED_MIME_FOR_EXTENSION = {
    ".xlsx": {
        XLSX_MIME,
        "application/zip",
        "application/octet-stream",
        "application/vnd.ms-excel",
    },
    ".csv": {
        CSV_MIME,
        "text/plain",
        "application/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
    },
    ".docx": {
        DOCX_MIME,
        "application/zip",
        "application/octet-stream",
        "application/msword",
    },
    ".eml": {
        EMAIL_MIME,
        "message/global",
        "text/rfc822",
        # libmagic answers `text/plain` for a message whose headers are
        # too sparse to classify; the header check below is what decides.
        "text/plain",
        "application/octet-stream",
    },
    ".jpg": {JPEG_MIME},
    ".jpeg": {JPEG_MIME},
    ".png": {PNG_MIME},
}


# An OOXML file is a zip; this is the directory that proves which kind.
ZIP_MARKER_FOR_EXTENSION = {
    ".xlsx": "xl/",
    ".docx": "word/",
}


def detect_file_type(file):
    """
    The MIME type, read from the bytes rather than the extension.

    Reading moves the pointer, so it is rewound before returning: the
    caller still has to save the file.
    """

    file_type = magic.from_buffer(file.read(2048), mime=True)
    file.seek(0)

    return file_type


def _extension(file):
    return Path(getattr(file, "name", "") or "").suffix.lower()


def zip_contains(file, prefix):
    """
    True when the upload is a zip archive holding a `prefix` directory.

    A `.xlsx` is a zip with `xl/`, a `.docx` is a zip with `word/`. A
    renamed `.zip` has neither, and would otherwise be accepted on its
    extension alone and only fail later, in a worker, as an opaque
    `Failed` row.
    """

    file.seek(0)

    try:
        with zipfile.ZipFile(file) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False
    finally:
        file.seek(0)

    return any(name.startswith(prefix) for name in names)


def is_utf8_text(file):
    """
    True when the first 64 KB decode as UTF-8.

    The incremental decoder is used so a multi-byte character cut in
    half by the read boundary is not mistaken for a broken file.
    """

    file.seek(0)

    try:
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        decoder.decode(file.read(65536), final=False)
    except UnicodeDecodeError:
        return False
    finally:
        file.seek(0)

    return True


def effective_file_type(file):
    """
    The type to store and to dispatch on.

    Returns `INVALID_FILE_TYPE` whenever the extension and the bytes
    disagree, so `validate_upload` rejects the file instead of the
    worker discovering it later. It must not fall back to the raw MIME:
    the MIME of a broken `.csv` is `text/plain`, which is allowed, and
    the upload would pass validation only to fail as a `Failed` row.
    """

    mime = detect_file_type(file)
    extension = _extension(file)

    expected = EXTENSION_FILE_TYPES.get(extension)

    if expected is None:
        return mime

    if mime not in ACCEPTED_MIME_FOR_EXTENSION[extension]:
        return INVALID_FILE_TYPE

    marker = ZIP_MARKER_FOR_EXTENSION.get(extension)

    if marker and not zip_contains(file, marker):
        return INVALID_FILE_TYPE

    if extension == ".csv" and not is_utf8_text(file):
        return INVALID_FILE_TYPE

    if extension == ".eml":
        # Not a UTF-8 check: an email body is whatever the sender's
        # client produced, and it says so in its own headers. What is
        # checked is the shape — an RFC 822 header block at the top —
        # which is what a renamed `.txt` cannot fake.
        from .extractors.email import looks_like_email

        if not looks_like_email(file):
            return INVALID_FILE_TYPE

    return expected
