FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Native tools for the OCR fallback. Both the API and the worker use the
# same image: the worker rasterises scanned pages (poppler) and runs
# Tesseract. The API does not call either (its preview reads stored
# chunks), but sharing one image keeps the worker self-contained.
# Persian and English traineddata are installed explicitly — the base
# `tesseract-ocr` package ships `eng` only on Debian slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libmagic1 \
        tesseract-ocr \
        tesseract-ocr-fas \
        tesseract-ocr-eng \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app \
    && adduser --system --ingroup app app

COPY requirements-django.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-django.txt

COPY --chown=app:app . .

RUN mkdir -p /app/media \
    && chown app:app /app/media

USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--worker-class", "gthread", "--threads", "8", "--timeout", "300", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]