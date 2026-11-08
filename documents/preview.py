"""
Full-text preview of a stored document.

The citation drawer shows the retrieved chunk, but the user usually
wants to see *where* that passage sits in the original file. This module
re-uses the same extractors as the ingestion pipeline, so the preview
text matches what was indexed.
"""

import logging

from .extractors.pdf import extract_pdf_text
from .extractors.txt import extract_txt_text
from .extractors.word import extract_word_text


logger = logging.getLogger(__name__)

# A 5 MB PDF can expand to a lot of text. The drawer only needs enough
# context around the matches, and the browser has to render it.
MAX_PREVIEW_CHARACTERS = 120_000

WORD_FILE_TYPES = (
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)


class PreviewUnavailable(Exception):
    """The stored file cannot be rendered as text."""


class PreviewFileMissing(PreviewUnavailable):
    """The document row exists but its file is gone from storage."""


def extract_document_text(document, max_characters=MAX_PREVIEW_CHARACTERS):
    """
    Return `(text, truncated)` for a document.

    Raises `PreviewUnavailable` when the file is gone or its type cannot
    be extracted.
    """

    try:
        handle = document.file_path.open("rb")
    except (FileNotFoundError, ValueError) as exc:
        raise PreviewFileMissing(
            "The stored file is no longer available."
        ) from exc

    with handle:
        try:
            if document.file_type == "application/pdf":
                text = extract_pdf_text(handle)

            elif document.file_type == "text/plain":
                text = extract_txt_text(handle)

            elif document.file_type in WORD_FILE_TYPES:
                text = extract_word_text(handle)

            else:
                raise PreviewUnavailable(
                    f"Cannot preview files of type {document.file_type}."
                )
        except PreviewUnavailable:
            raise
        except Exception as exc:
            # A corrupt file must not turn into a 500 in the drawer.
            logger.warning(
                "Could not extract preview text for document %s: %s",
                document.id,
                exc,
            )
            raise PreviewUnavailable(
                "This file cannot be displayed as text. "
                "Use the original file link instead."
            ) from exc

    text = text or ""
    truncated = len(text) > max_characters

    return text[:max_characters], truncated
