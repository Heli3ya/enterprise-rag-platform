from typing import BinaryIO

from docx import Document


def extract_word_text(file: BinaryIO) -> str:
    """
    Extract clean text from all non-empty paragraphs of a DOCX file.

    Args:
        file: A binary file-like object containing a DOCX document.

    Returns:
        Extracted paragraphs as a single cleaned string.
    """
    document = Document(file)

    paragraphs = []

    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split())

        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)