from typing import BinaryIO

from pypdf import PdfReader


def extract_pdf_text(file: BinaryIO) -> str:
    """
    Extract clean text from all pages of a text-based PDF.

    Args:
        file: A binary file-like object containing PDF data.

    Returns:
        The extracted text as a single cleaned string.

    Raises:
        ValueError: If the PDF contains no extractable text.
    """
    reader = PdfReader(file)

    pages_text = []

    for page in reader.pages:
        text = page.extract_text()

        if text:
            cleaned_text = " ".join(text.split())
            if cleaned_text:
                pages_text.append(cleaned_text)

    result = "\n\n".join(pages_text)

    if not result:
        raise ValueError("No extractable text found in PDF.")

    return result