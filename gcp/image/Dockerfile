# Stage 1: system deps + Python deps (cached layer)
FROM python:3.12-slim-bookworm AS deps

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libsndfile1 ffmpeg curl gnupg && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

WORKDIR /opt/bmt

# Copy only dependency metadata first (layer caching)
COPY gcp/image/pyproject.toml gcp/image/uv.lock /opt/bmt/gcp/image/
COPY gcp/__init__.py /opt/bmt/gcp/__init__.py
COPY gcp/image/__init__.py /opt/bmt/gcp/image/__init__.py

# Install deps into a project-local .venv
RUN cd /opt/bmt/gcp/image && uv sync --frozen --no-dev --no-editable

# Stage 2: application code
FROM deps AS app

# Copy the full gcp/image package (managers, contracts, schemas, scripts, etc.)
COPY gcp/__init__.py /opt/bmt/gcp/__init__.py
COPY gcp/image/ /opt/bmt/gcp/image/

ENV PYTHONPATH=/opt/bmt
ENV PATH="/opt/bmt/gcp/image/.venv/bin:$PATH"

# Config via BMT_CONFIG env var pointing to a JSON payload file,
# or mount at /etc/bmt/config.json (well-known path)
CMD ["python", "gcp/image/main.py"]
