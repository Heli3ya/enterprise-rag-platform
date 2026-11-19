"""
Sub-task 2 — the Python side of OCR.

pytesseract and pdf2image are thin wrappers: pinning them and their
Pillow dependency makes the image and a developer venv resolve the same
code. The other half of this file pins the *contract* with the native
binaries: language selection, a bounded timeout, and an explicit error
when the image is misconfigured. None of these tests needs Tesseract
installed on the machine running pytest.

    ./venv/Scripts/python.exe -m pytest tests/test_ocr_python_dependencies.py -q
"""

import importlib.metadata
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from documents.extractors import ocr


ROOT = Path(__file__).resolve().parents[1]


def requirements():
    return (
        (ROOT / "requirements-django.txt")
        .read_text(encoding="utf-8-sig")
        .lower()
    )


@pytest.mark.parametrize(
    ("package", "pin"),
    [
        ("pytesseract", "pytesseract==0.3.13"),
        ("pdf2image", "pdf2image==1.17.0"),
        ("pillow", "pillow==11.3.0"),
    ],
)
def test_ocr_dependencies_are_pinned_and_installed(package, pin):
    assert pin in requirements()
    assert importlib.metadata.version(package)


def test_default_languages_include_persian():
    assert "fas" in ocr.OCR_LANGUAGES.split("+")


def test_a_missing_binary_is_reported_before_any_conversion():
    ocr.tesseract_languages.cache_clear()

    try:
        with patch.object(ocr.shutil, "which", return_value=None):
            with pytest.raises(ocr.OCRUnavailableError, match="tesseract-ocr-fas"):
                ocr.require_tesseract()
    finally:
        ocr.tesseract_languages.cache_clear()


def test_a_missing_language_pack_is_reported():
    ocr.tesseract_languages.cache_clear()

    try:
        with patch.object(
            ocr.shutil, "which", return_value="/usr/bin/tesseract"
        ), patch(
            "pytesseract.get_languages", return_value=["eng"]
        ):
            with pytest.raises(ocr.OCRUnavailableError, match="tesseract-ocr-fas"):
                ocr.require_tesseract()
    finally:
        ocr.tesseract_languages.cache_clear()


def test_image_to_text_passes_language_config_and_timeout():
    image = Image.new("L", (40, 20), color=255)

    with patch.object(ocr, "require_tesseract"), patch(
        "pytesseract.image_to_string", return_value="صورت حساب ۱۴۰۲"
    ) as recognize:
        text = ocr.image_to_text(image)

    assert text == "صورت حساب ۱۴۰۲"
    kwargs = recognize.call_args.kwargs
    assert kwargs["lang"] == ocr.OCR_LANGUAGES
    assert kwargs["config"] == ocr.OCR_CONFIG
    assert kwargs["timeout"] == ocr.OCR_TIMEOUT


def test_persian_character_variants_are_folded_but_digits_are_not():
    # Tesseract may emit ي/ك; a typed query uses ی/ک. Digits stay as
    # recognised so a code such as BR-60 is not silently rewritten.
    text = "  شماره\t BR-60   وusp  \n  كد : ۱۲۳  "

    assert ocr.normalize_ocr_text(text) == "شماره BR-60 وusp\nکد : ۱۲۳"


def test_an_oversized_image_is_rejected_before_tesseract_starts():
    ocr.tesseract_languages.cache_clear()

    huge = Image.new("L", (6000, 6000), color=255)

    with patch.object(ocr, "require_tesseract"):
        with pytest.raises(ValueError, match="too large"):
            ocr.image_to_text(huge)
