from io import BufferedIOBase


def extract_txt_text(file: BufferedIOBase) -> str:
    """
    Extract clean UTF-8 text from a TXT file.

    Args:
        file: A binary file-like object containing UTF-8 text.

    Returns:
        Clean extracted text as a string.
    """
    content = file.read()

    text = content.decode("utf-8")

    return text.strip()