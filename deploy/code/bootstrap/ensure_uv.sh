#!/usr/bin/env bash
# Resolve an executable uv binary for bootstrap.
# Order:
#   1. BMT_UV_BIN override (if executable)
#   2. Existing uv on PATH
#   3. Fetch pinned uv artifact from code namespace and verify checksum
#
# Exports:
#   UV_BIN - absolute path to selected uv binary
#   PATH   - prepends installed uv directory when fetched from code namespace

set -euo pipefail

_extract_sha() {
  local sha_file="$1"
  awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      if (match($0, /^[[:space:]]*([0-9a-fA-F]{64})[[:space:]]+(\*?uv)?[[:space:]]*$/, m)) {
        print tolower(m[1]);
        exit 0;
      }
      exit 2;
    }
    END {
      if (NR == 0) {
        exit 1;
      }
    }
  ' "$sha_file"
}

_download_and_install_uv() {
  local code_root="$1"  # e.g. gs://BUCKET/code
  local install_dir="$2"
  local tmp_dir
  local uv_uri="${code_root}/_tools/uv/linux-x86_64/uv"
  local sha_uri="${code_root}/_tools/uv/linux-x86_64/uv.sha256"
  tmp_dir="$(mktemp -d -t bmt-uv-XXXXXX)"
  trap "rm -rf '${tmp_dir}'" RETURN

  gcloud storage cp "${uv_uri}" "${tmp_dir}/uv" --quiet
  gcloud storage cp "${sha_uri}" "${tmp_dir}/uv.sha256" --quiet

  local expected actual
  expected="$(_extract_sha "${tmp_dir}/uv.sha256" || true)"
  if [[ -z "$expected" ]]; then
    echo "::error::Invalid uv checksum file at ${sha_uri}" >&2
    return 1
  fi

  actual="$(sha256sum "${tmp_dir}/uv" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "::error::Pinned uv checksum mismatch for ${uv_uri}" >&2
    echo "::error::Expected ${expected}, got ${actual}" >&2
    return 1
  fi

  mkdir -p "${install_dir}"
  install -m 0755 "${tmp_dir}/uv" "${install_dir}/uv"
  printf '%s  uv\n' "${expected}" > "${install_dir}/uv.sha256"
}

main() {
  if [[ -n "${BMT_UV_BIN:-}" ]]; then
    if [[ ! -x "${BMT_UV_BIN}" ]]; then
      echo "::error::BMT_UV_BIN is not executable: ${BMT_UV_BIN}" >&2
      return 1
    fi
    UV_BIN="${BMT_UV_BIN}"
    export UV_BIN
    echo "Using uv from BMT_UV_BIN=${UV_BIN}"
    return 0
  fi

  if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
    export UV_BIN
    echo "Using existing uv on PATH: ${UV_BIN}"
    return 0
  fi

  local bucket code_root install_dir bmt_repo_root
  bucket="${GCS_BUCKET:-}"
  bmt_repo_root="${BMT_REPO_ROOT:-/opt/bmt}"
  code_root="gs://${bucket}/code"
  install_dir="${bmt_repo_root}/.tools/uv/linux-x86_64"

  # Check if a pre-synced uv binary exists in the code namespace (_tools, synced by startup_wrapper.sh).
  # This avoids a redundant GCS download when the binary is already on disk.
  local synced_uv="${bmt_repo_root}/_tools/uv/linux-x86_64/uv"
  local synced_sha="${bmt_repo_root}/_tools/uv/linux-x86_64/uv.sha256"
  if [[ -x "${synced_uv}" && -f "${synced_sha}" ]]; then
    local expected actual
    expected="$(_extract_sha "${synced_sha}")"
    actual="$(sha256sum "${synced_uv}" | awk '{print $1}')"
    if [[ -n "${expected}" && "${actual}" == "${expected}" ]]; then
      UV_BIN="${synced_uv}"
      export UV_BIN
      PATH="$(dirname "${synced_uv}"):${PATH}"
      export PATH
      echo "Using pre-synced uv from ${synced_uv}"
      return 0
    fi
  fi

  if [[ -z "$bucket" ]]; then
    echo "::error::GCS_BUCKET is required to fetch pinned uv artifact." >&2
    return 1
  fi
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "::error::gcloud CLI not found; cannot fetch pinned uv artifact." >&2
    return 1
  fi

  _download_and_install_uv "${code_root}" "${install_dir}"
  UV_BIN="${install_dir}/uv"
  if [[ ! -x "${UV_BIN}" ]]; then
    echo "::error::Installed uv is missing or not executable: ${UV_BIN}" >&2
    return 1
  fi
  PATH="${install_dir}:${PATH}"
  export UV_BIN PATH
  echo "Installed pinned uv from ${code_root}/_tools/uv/linux-x86_64/uv"
}

main "$@"
