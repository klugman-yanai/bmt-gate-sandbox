# Stage 1: system deps + Python deps (cached layer)
# Ubuntu 26.04 (glibc 2.43) required by libKardome.so 7.2.20+.
# Python 3.12 not in Ubuntu 26.04 default repos — installed via uv managed Python.
FROM ubuntu:26.04 AS deps

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  ffmpeg \
  libsndfile1 && \
  rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

WORKDIR /opt/bmt

# Python 3.12 not in Ubuntu 26.04 repos; install via uv managed Python.
RUN uv python install 3.12

# Copy workspace metadata for layer caching + local workspace member resolution.
# bmt-sdk is a workspace-local package (sdk/); uv needs the full workspace to resolve it.
COPY pyproject.toml uv.lock ./
COPY sdk/ sdk/
COPY ci/pyproject.toml ci/
COPY runtime/pyproject.toml runtime/

# Install runtime deps via workspace resolution (resolves bmt-sdk from sdk/)
RUN uv sync --python 3.12 --no-dev --no-editable --package bmt-runtime

# Stage 2: application code
FROM deps AS app

# Copy the full runtime package (managers, contracts, schemas, scripts, etc.)
COPY runtime/ /opt/bmt/runtime/

ENV PYTHONPATH=/opt/bmt
ENV PATH="/opt/bmt/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Config via BMT_CONFIG env var pointing to a JSON payload file,
# or mount at /etc/bmt/config.json (well-known path)
CMD ["python", "-m", "runtime.main"]
