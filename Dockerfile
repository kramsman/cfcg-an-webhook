FROM python:3.12-slim

# Install system libraries needed by Pillow on Linux
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (better layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY cfcg_an_webhook/ cfcg_an_webhook/

# Cloud Run sets PORT; default to 8080
ENV PORT=8080

CMD uv run gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 cfcg_an_webhook.main:app
