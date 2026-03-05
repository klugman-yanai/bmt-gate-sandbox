# Cloud Run Job container for BMT VM Watcher (single-trigger mode).
#
# Entrypoint downloads code/ from GCS using WORKFLOW_RUN_ID and GCS_BUCKET,
# then runs vm_watcher.py in single-trigger mode (--workflow-run-id).
#
# Required env vars at runtime (injected via Cloud Run Job env or Secret Manager mounts):
#   GCS_BUCKET              — GCS bucket name (no gs:// prefix)
#   WORKFLOW_RUN_ID         — workflow run ID; injected by bmt execute-cloud-run-job
#
# Auth: the job service account must have roles/storage.objectUser on the bucket
#       and access to Secret Manager secrets for GitHub App credentials.

FROM python:3.12-slim

# Install gcloud CLI (needed by vm_watcher.py for all GCS operations)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        apt-transport-https \
        ca-certificates \
        gnupg \
    && echo "deb [signed-by=/usr/share/keyrings/cloud.google.asc] https://packages.cloud.google.com/apt cloud-sdk main" \
        > /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        -o /usr/share/keyrings/cloud.google.asc \
    && apt-get update && apt-get install -y --no-install-recommends google-cloud-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for dependency management (matches VM startup approach)
RUN pip install --no-cache-dir uv

# Copy the entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# vm_watcher.py and lib/ are downloaded at runtime from GCS (code/ namespace).
# This keeps the image decoupled from code version — update GCS to deploy new code.

ENTRYPOINT ["/app/entrypoint.sh"]
