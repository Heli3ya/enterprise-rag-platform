
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app \
    && adduser --system --ingroup app app

COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=app:app . .

# The reports directory must exist in the image: Docker initialises a
# named volume from the image path, and an existing directory keeps this
# ownership. Without it the volume is created as root and the service
# (running as `app`) cannot write its reports.
RUN mkdir -p /app/.cache/huggingface /app/evaluation/reports \
    && chown -R app:app /app

USER app

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
