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

# Copy only dependency metadata first (layer caching)
COPY gcp/image/pyproject.toml /opt/bmt/gcp/image/
COPY gcp/__init__.py /opt/bmt/gcp/__init__.py
COPY gcp/image/__init__.py /opt/bmt/gcp/image/__init__.py

# Install deps into a project-local .venv from pyproject dependencies.
# Do not rely on stale lock snapshots for runtime-critical deps.
RUN cd /opt/bmt/gcp/image && uv sync --python /usr/bin/python3.12 --no-dev --no-editable

# Stage 2: application code
FROM deps AS app

# Copy the full gcp/image package (managers, contracts, schemas, scripts, etc.)
COPY gcp/__init__.py /opt/bmt/gcp/__init__.py
COPY gcp/image/ /opt/bmt/gcp/image/

ENV PYTHONPATH=/opt/bmt
ENV PATH="/opt/bmt/gcp/image/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Config via BMT_CONFIG env var pointing to a JSON payload file,
# or mount at /etc/bmt/config.json (well-known path)
#
# Use -m so sys.path[0] is not gcp/image/ — otherwise `import github` resolves to
# gcp/image/github/ and shadows PyGithub (ImportError: GithubException).
CMD ["python", "-m", "gcp.image.main"]
