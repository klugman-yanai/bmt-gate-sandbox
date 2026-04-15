# Stage 1: system deps + Python deps (cached layer)
# Base must remain Ubuntu 22.04: kardome_runner and libkardome.so require this
# environment (glibc/libstdc++ defaults) for Cloud Run–native execution.
FROM ubuntu:22.04 AS deps

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  gnupg \
  software-properties-common \
  ffmpeg \
  libsndfile1 && \
  add-apt-repository ppa:deadsnakes/ppa && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
  python3.12 \
  python3.12-venv && \
  rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

WORKDIR /opt/bmt

# Copy workspace metadata for layer caching + local workspace member resolution.
# bmt-sdk is a workspace-local package (sdk/); uv needs the full workspace to resolve it.
COPY pyproject.toml uv.lock ./
COPY sdk/ sdk/
COPY ci/pyproject.toml ci/
COPY runtime/pyproject.toml runtime/

# Install runtime deps via workspace resolution (resolves bmt-sdk from sdk/)
RUN uv sync --python /usr/bin/python3.12 --no-dev --no-editable --package bmt-runtime

# Stage 2: application code
FROM deps AS app

# Copy the full runtime package (managers, contracts, schemas, scripts, etc.)
COPY runtime/ /opt/bmt/runtime/

ENV PYTHONPATH=/opt/bmt
ENV PATH="/opt/bmt/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Config via BMT_CONFIG env var pointing to a JSON payload file,
# or mount at /etc/bmt/config.json (well-known path)
CMD ["python", "runtime/main.py"]
