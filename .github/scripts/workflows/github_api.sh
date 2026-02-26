#!/usr/bin/env bash
# Shared GitHub API helpers for workflow shell commands.
# shellcheck shell=bash

gh_require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "::error::Required command not found: $1" >&2
    return 1
  fi
}

gh_api_request() {
  local method="$1"
  local url="$2"
  local token="$3"
  local payload="${4:-}"
  local output_file="${5:-}"
  local attempts=3
  local delay=1
  local body_file=""
  local http_code=""
  local attempt=0
  local curl_args=()

  gh_require_cmd curl || return 1

  if [[ -n "$output_file" ]]; then
    body_file="$output_file"
    : >"$body_file"
  else
    body_file="$(mktemp)"
  fi

  for attempt in $(seq 1 "$attempts"); do
    curl_args=(
      -sS
      -w '%{http_code}'
      -o "$body_file"
      -X "$method"
      -H "Accept: application/vnd.github+json"
      -H "Authorization: Bearer ${token}"
      -H "X-GitHub-Api-Version: 2022-11-28"
      "$url"
    )
    if [[ -n "$payload" ]]; then
      curl_args+=(-H "Content-Type: application/json" -d "$payload")
    fi

    http_code="$(curl "${curl_args[@]}")" || {
      if [[ "$attempt" -lt "$attempts" ]]; then
        sleep "$delay"
        delay=$((delay * 2))
        continue
      fi
      echo "::error::GitHub API ${method} ${url} failed (transport error)." >&2
      [[ -s "$body_file" ]] && sed -n '1,120p' "$body_file" >&2 || true
      [[ -z "$output_file" ]] && rm -f "$body_file"
      return 1
    }

    if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
      [[ -z "$output_file" ]] && rm -f "$body_file"
      return 0
    fi

    if { [[ "$http_code" == "429" ]] || [[ "$http_code" =~ ^5[0-9][0-9]$ ]]; } && [[ "$attempt" -lt "$attempts" ]]; then
      sleep "$delay"
      delay=$((delay * 2))
      continue
    fi

    echo "::error::GitHub API ${method} ${url} failed (HTTP ${http_code})." >&2
    [[ -s "$body_file" ]] && sed -n '1,120p' "$body_file" >&2 || true
    [[ -z "$output_file" ]] && rm -f "$body_file"
    return 1
  done

  [[ -z "$output_file" ]] && rm -f "$body_file"
  echo "::error::GitHub API ${method} ${url} exhausted retries." >&2
  return 1
}

gh_post_status() {
  local repository="$1"
  local sha="$2"
  local token="$3"
  local state="$4"
  local context="$5"
  local description="$6"
  local target_url="${7:-}"
  local payload=""

  gh_require_cmd jq || return 1

  description="${description:0:140}"
  if [[ -n "$target_url" ]]; then
    payload="$(jq -n \
      --arg s "$state" \
      --arg c "$context" \
      --arg d "$description" \
      --arg t "$target_url" \
      '{state:$s,context:$c,description:$d,target_url:$t}')"
  else
    payload="$(jq -n \
      --arg s "$state" \
      --arg c "$context" \
      --arg d "$description" \
      '{state:$s,context:$c,description:$d}')"
  fi

  gh_api_request "POST" "https://api.github.com/repos/${repository}/statuses/${sha}" "$token" "$payload"
}

gh_post_pr_comment() {
  local repository="$1"
  local pr_number="$2"
  local token="$3"
  local body="$4"
  local payload=""

  gh_require_cmd jq || return 1

  payload="$(jq -n --arg body "$body" '{body:$body}')"
  gh_api_request "POST" "https://api.github.com/repos/${repository}/issues/${pr_number}/comments" "$token" "$payload"
}

gh_latest_status_state() {
  local repository="$1"
  local sha="$2"
  local token="$3"
  local context="$4"
  local tmp=""
  local state=""

  gh_require_cmd jq || return 1

  tmp="$(mktemp)"
  if ! gh_api_request "GET" "https://api.github.com/repos/${repository}/commits/${sha}/status?per_page=100" "$token" "" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi

  state="$(jq -r --arg c "$context" '[.statuses[]? | select(.context == $c) | .state][0] // ""' "$tmp" 2>/dev/null || true)"
  rm -f "$tmp"
  printf '%s' "$state"
}

gh_should_post_failure_status() {
  local repository="$1"
  local sha="$2"
  local token="$3"
  local context="$4"
  local latest_state=""

  if ! latest_state="$(gh_latest_status_state "$repository" "$sha" "$token" "$context")"; then
    echo "::warning::Could not read latest status for ${repository}@${sha} (context=${context}); posting failure fail-safe."
    return 0
  fi

  case "$latest_state" in
    ""|pending)
      return 0
      ;;
    success|failure|error)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}
