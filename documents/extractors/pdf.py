from io import BytesIO
from typing import BinaryIO

from pypdf import PdfReader

from .ocr import ocr_pdf_pages


# Below this many characters a "text" page is almost always a scan with
# a stray header/footer, or a font without a ToUnicode map. OCR is the
# only way to get the body out of it.
SELECTABLE_TEXT_MIN_CHARS = 20


class NoSelectableTextError(ValueError):
    """A PDF has no usable text layer and OCR was not allowed."""


def extract_pdf_text(file: BinaryIO, allow_ocr: bool = True) -> str:
    """
    Extract text from a PDF, falling back to OCR page by page.

    A mixed PDF — a typed cover sheet followed by scanned appendices —
    must not be treated as one or the other: the text layer is kept
    where it exists and only the image-only pages go through OCR.

    Args:
        file: A binary file-like object containing PDF data.
        allow_ocr: Set to False for the synchronous preview path, where
            starting Tesseract in a web worker would block other users.

    Returns:
        The extracted text as a single string, pages in original order.

    Raises:
        NoSelectableTextError: No text layer and OCR was disabled.
        ValueError: Nothing readable came out of the document.
    """

    pdf_bytes = file.read()
    reader = PdfReader(BytesIO(pdf_bytes))

    pages_text = []
    image_only_pages = []

    for index, page in enumerate(reader.pages):
        text = " ".join((page.extract_text() or "").split())

        if len(text) >= SELECTABLE_TEXT_MIN_CHARS:
            pages_text.append((index, text))
        else:
            image_only_pages.append(index)

    if image_only_pages and allow_ocr:
        recognized = ocr_pdf_pages(pdf_bytes, image_only_pages)

        for index in image_only_pages:
            text = recognized.get(index, "")

            if text:
                pages_text.append((index, text))

    if not pages_text and not allow_ocr:
        raise NoSelectableTextError(
            "This PDF has no selectable text. It needs OCR."
        )

    pages_text.sort(key=lambda item: item[0])
    result = "\n\n".join(text for _, text in pages_text)

    if not result:
        raise ValueError("No extractable text found in PDF.")

    return result
