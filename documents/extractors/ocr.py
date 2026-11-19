"""
OCR helpers for scans and photographs of documents.

Two native processes do the heavy lifting: poppler rasterises PDF pages
and Tesseract recognises the glyphs. Pillow only normalises the image
before it is handed over. Nothing here imports a Django model, so the
module can be tested without a database.

Cost control matters more than elegance here. OCR is CPU bound and runs
in the single Celery worker slot that also embeds text, so this module:

* never rasterises a page that already has selectable text (the caller
  in `pdf.py` decides that);
* converts pages in small contiguous batches instead of holding a
  whole 20-page document as PIL images;
* caps DPI, image size, page count and per-page time;
* fails loudly when a language pack is missing instead of returning
  half-readable text that would poison the index.
"""

import logging
import os
import shutil
from functools import lru_cache

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


def _positive_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "fas+eng")
OCR_DPI = _positive_int("OCR_DPI", 150)
OCR_TIMEOUT = _positive_int("OCR_TIMEOUT", 120)
OCR_MAX_PAGES = _positive_int("OCR_MAX_PAGES", 20)

# More than four A4 pages at 150 dpi is enough to make the worker's
# memory jump without a matching speed gain.
OCR_PAGE_BATCH = 4

# A 5 MB JPEG can still decode into a gigantic bitmap. Refuse it before
# Tesseract tries to allocate a second copy.
OCR_MAX_IMAGE_PIXELS = 25_000_000

# LSTM-only engine, automatic page segmentation: it handles a stamped
# letter better than the legacy engine and does not need a box file.
OCR_CONFIG = "--oem 1 --psm 3"

# Tesseract's Persian model occasionally emits the Arabic forms of two
# letters. Folding them makes OCR text match a typed Persian query and
# the spelling used in the rest of the index.
_CHARACTER_FOLDS = str.maketrans(
    {
        "\u064a": "\u06cc",  # ي -> ی
        "\u0643": "\u06a9",  # ك -> ک
    }
)


class OCRUnavailableError(RuntimeError):
    """The native OCR stack is missing or misconfigured."""


class OCRPageLimitError(ValueError):
    """The document exceeds the configured page budget."""


@lru_cache(maxsize=1)
def tesseract_languages():
    """Languages Tesseract actually has, checked once per process."""

    if not shutil.which("tesseract"):
        return frozenset()

    try:
        import pytesseract

        return frozenset(pytesseract.get_languages(config=""))
    except Exception as exc:
        # A broken binary must degrade to a clear upload error, not to
        # an exception in an unrelated code path.
        logger.warning("Could not list Tesseract languages: %s", exc)
        return frozenset()


def require_tesseract():
    """Fail early with a message an operator can act on."""

    if not shutil.which("tesseract"):
        raise OCRUnavailableError(
            "Tesseract is not installed in the worker image. "
            "Rebuild the image after installing tesseract-ocr, "
            "tesseract-ocr-fas and poppler-utils."
        )

    languages = tesseract_languages()

    if not languages:
        return

    missing = [
        language
        for language in OCR_LANGUAGES.split("+")
        if language not in languages
    ]

    if missing:
        raise OCRUnavailableError(
            "Tesseract is missing the language pack(s): "
            + ", ".join(missing)
            + ". Install tesseract-ocr-"
            + " tesseract-ocr-".join(missing)
            + "."
        )


def normalize_ocr_text(text):
    """Fold character variants and tidy whitespace without touching digits."""

    folded = (text or "").translate(_CHARACTER_FOLDS)
    lines = [" ".join(line.split()) for line in folded.splitlines()]

    return "\n".join(line for line in lines if line)


def _prepare_image(image):
    if image.width * image.height > OCR_MAX_IMAGE_PIXELS:
        raise ValueError(
            "Image is too large to process with OCR "
            f"({image.width}x{image.height} pixels)."
        )

    grayscale = image.convert("L")

    return ImageOps.autocontrast(grayscale)


def image_to_text(image, *, languages=None):
    """Recognise one PIL image. Kept separate so tests can inject one."""

    require_tesseract()

    import pytesseract

    prepared = _prepare_image(image)

    return normalize_ocr_text(
        pytesseract.image_to_string(
            prepared,
            lang=languages or OCR_LANGUAGES,
            config=OCR_CONFIG,
            timeout=OCR_TIMEOUT,
        )
    )


def extract_image_text(file):
    """OCR a JPEG or PNG upload and return its text."""

    file.seek(0)

    with Image.open(file) as image:
        # A phone photograph is often rotated through EXIF rather than
        # pixels. Without this, Tesseract reads sideways text.
        upright = ImageOps.exif_transpose(image)
        upright.load()
        text = image_to_text(upright)

    if not text:
        raise ValueError("No text could be read from this image.")

    return text


def _contiguous_runs(page_indices):
    runs = []

    for index in page_indices:
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])

    return runs


def ocr_pdf_pages(pdf_bytes, page_indices, *, dpi=None):
    """
    Recognise selected zero-based pages of a PDF.

    Returns a `{page_index: text}` mapping. Pages are converted in
    contiguous batches so a scan whose text pages are interleaved does
    not pay for pages it does not need.
    """

    indices = sorted(set(page_indices))

    if not indices:
        return {}

    if len(indices) > OCR_MAX_PAGES:
        raise OCRPageLimitError(
            f"This PDF needs OCR on {len(indices)} pages; the limit is "
            f"{OCR_MAX_PAGES}. Split the scan into smaller files."
        )

    require_tesseract()

    from pdf2image import convert_from_bytes

    results = {}
    render_dpi = dpi or OCR_DPI

    for run in _contiguous_runs(indices):
        for start in range(0, len(run), OCR_PAGE_BATCH):
            batch = run[start:start + OCR_PAGE_BATCH]
            first, last = batch[0] + 1, batch[-1] + 1

            images = convert_from_bytes(
                pdf_bytes,
                dpi=render_dpi,
                first_page=first,
                last_page=last,
            )

            try:
                for offset, image in enumerate(images):
                    page_index = first - 1 + offset

                    if page_index in batch:
                        results[page_index] = image_to_text(image)
            finally:
                for image in images:
                    image.close()

    return results
