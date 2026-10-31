# One image for both the API (dashboard) and the worker (daily pipeline).

# --- 1. Build the React dashboard ------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Python runtime -----------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Embedding model is downloaded once into a volume, not baked into the image.
    FASTEMBED_CACHE_PATH=/cache/fastembed \
    HF_HOME=/cache/huggingface

RUN useradd --create-home --uid 1000 app
WORKDIR /app/backend

# Pinned dependencies first (cached layer), then the app itself without re-resolving.
# The pip cache mount keeps downloaded wheels between builds (it is not part of the image),
# so a build interrupted by a flaky network resumes instead of starting over.
COPY backend/requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 120 -r requirements.lock
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir --no-deps .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/config ./config
COPY --from=frontend /frontend/dist /app/frontend/dist

RUN mkdir -p /cache /data && chown -R app:app /cache /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
