"""
Sub-task 1 — the OCR engine is part of the image, not the developer's laptop.

The worker is a Debian slim container: it does not inherit a host
Tesseract installation. If the traineddata is missing from the image,
`fas` recognition silently falls back to English and a Persian letter
comes out as a pile of Latin characters. These tests pin the image and
the compose wiring, while the separate docker command below proves the
binary really runs in the built image.

    docker compose exec -T django sh -c \
      'tesseract --list-langs 2>&1 | grep -E "^(fas|eng)$" && pdftoppm -v'
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dockerfile_text():
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def compose_text():
    return (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_image_installs_tesseract_with_persian_and_english():
    dockerfile = dockerfile_text()

    assert "tesseract-ocr" in dockerfile
    assert "tesseract-ocr-fas" in dockerfile
    assert "tesseract-ocr-eng" in dockerfile


def test_image_installs_poppler_for_pdf_rasterisation():
    # pdf2image is only a wrapper; without pdftoppm it raises on the
    # first scanned page, after the upload has already been accepted.
    assert "poppler-utils" in dockerfile_text()


def test_native_packages_share_the_cached_apt_layer():
    dockerfile = dockerfile_text()

    assert "--no-install-recommends" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def test_worker_receives_the_ocr_configuration():
    compose = compose_text()
    worker = compose.split("  celery_worker:", 1)[1]

    for key in ("OCR_LANGUAGES", "OCR_DPI", "OCR_TIMEOUT", "OCR_MAX_PAGES"):
        assert key in worker


def test_env_example_documents_the_ocr_settings():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "OCR_LANGUAGES=fas+eng" in env
    assert "OCR_MAX_PAGES=" in env


def test_web_process_does_not_import_tesseract_at_module_scope():
    """
    OCR is a worker concern. An import in the web path would put
    pytesseract and Pillow into every gunicorn process for a branch the
    API never executes.
    """

    views = (ROOT / "documents" / "views.py").read_text(encoding="utf-8")

    assert "pytesseract" not in views
    assert "pdf2image" not in views
