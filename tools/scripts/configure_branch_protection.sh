#!/usr/bin/env bash
# configure_branch_protection.sh — manage the "BMT Gate" required-status-check
# ruleset on a target repo + branch. Defaults to **dry-run** (no API writes).
# Pass --apply to actually create or update the ruleset.
#
# Today (2026-04) bmt-gcloud already has a matching ruleset on dev
# (id 12946785, name "Dev Branch Protection - BMT Gate"). This script's job
# is to make that posture (a) reproducible across forks/branches and
# (b) trivially extendable to ci/check-bmt-gate or downstream consumers
# such as Kardome-org/core-main once the runner-crash work lands and the
# gate is ready to be enforced everywhere.
#
# Why a script and not Pulumi/Terraform: branch protection lives in the
# GitHub plane (not the GCP plane), and we want a one-line, reviewable
# `bash …` we can run from a workstation or a maintenance workflow without
# pulling in the Pulumi state. The shape of the ruleset mirrors what we
# already have in production (`gh api repos/<repo>/rulesets/12946785`):
#
#   target: branch
#   conditions.ref_name.include: ["refs/heads/<branch>"]
#   rules:
#     - deletion
#     - non_fast_forward
#     - required_status_checks:
#         required_status_checks: [{context: "<status_context>"}]
#         strict_required_status_checks_policy: false
#         do_not_enforce_on_create: true
#
# Flags:
#   --repo OWNER/NAME     Target repo (default: $GH_REPO or current repo)
#   --branch NAME         Protected branch (default: dev)
#   --status-context STR  Required status check context (default: BMT Gate)
#   --integration-id ID   Pin the check to a GitHub App ID (default: unset).
#                         Production bmt-gcloud uses 2899213; leave unset
#                         to accept any actor that posts the context.
#   --name NAME           Ruleset name (default: derived from branch+context)
#   --apply               Actually POST/PUT the ruleset. Without this flag
#                         the script prints the resolved JSON payload only.
#   --update ID           Update an existing ruleset by id (PUT) instead of
#                         POST. Mutually exclusive with the auto-create path.
#   --enforcement MODE    active | evaluate | disabled (default: evaluate
#                         on create — "do not enforce yet" per CLAUDE.md;
#                         use --enforce-active to force active).
#   --enforce-active      Shortcut for --enforcement active.
#   --bypass-actor JSON   Optional repeated bypass actor entry, raw JSON
#                         (e.g. '{"actor_id":12345,"actor_type":"Team",
#                         "bypass_mode":"pull_request"}'). May be passed
#                         multiple times.
#   -h | --help           Print this help and exit.
#
# Environment:
#   GH_TOKEN / GITHUB_TOKEN   Used by `gh api`. Must have `repo` scope.
#
# Examples:
#   # Print what would be created on Kardome-org/core-main dev (no writes):
#   tools/scripts/configure_branch_protection.sh \
#       --repo Kardome-org/core-main --branch dev
#
#   # Mirror the production posture on a fork (still in evaluate mode):
#   tools/scripts/configure_branch_protection.sh \
#       --repo my-org/bmt-gcloud --branch dev --apply
#
#   # Promote an existing ruleset (id 13168599) to enforce on core-main:
#   tools/scripts/configure_branch_protection.sh \
#       --repo Kardome-org/core-main --branch dev \
#       --update 13168599 --enforce-active --apply

set -euo pipefail

REPO=""
BRANCH="dev"
STATUS_CONTEXT="BMT Gate"
INTEGRATION_ID=""
RULESET_NAME=""
APPLY=0
UPDATE_ID=""
ENFORCEMENT="evaluate"
BYPASS_ACTORS=()

print_help() {
    sed -n '2,/^set -euo pipefail$/p' "$0" | sed 's/^# \{0,1\}//;/^set -euo pipefail$/d'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --status-context) STATUS_CONTEXT="$2"; shift 2 ;;
        --integration-id) INTEGRATION_ID="$2"; shift 2 ;;
        --name) RULESET_NAME="$2"; shift 2 ;;
        --apply) APPLY=1; shift ;;
        --update) UPDATE_ID="$2"; shift 2 ;;
        --enforcement) ENFORCEMENT="$2"; shift 2 ;;
        --enforce-active) ENFORCEMENT="active"; shift ;;
        --bypass-actor) BYPASS_ACTORS+=("$2"); shift 2 ;;
        -h|--help) print_help; exit 0 ;;
        *) echo "configure_branch_protection.sh: unknown flag: $1" >&2; exit 2 ;;
    esac
done

if ! command -v gh >/dev/null 2>&1; then
    echo "configure_branch_protection.sh: gh CLI not found in PATH" >&2
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "configure_branch_protection.sh: jq not found in PATH" >&2
    exit 1
fi

if [[ -z "$REPO" ]]; then
    REPO="${GH_REPO:-}"
fi
if [[ -z "$REPO" ]]; then
    if REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)"; then
        :
    else
        echo "configure_branch_protection.sh: --repo OWNER/NAME is required (no GH_REPO and not in a gh-known repo)" >&2
        exit 2
    fi
fi
if [[ -z "$RULESET_NAME" ]]; then
    RULESET_NAME="${BRANCH} branch protection — ${STATUS_CONTEXT}"
fi
case "$ENFORCEMENT" in
    active|evaluate|disabled) ;;
    *) echo "configure_branch_protection.sh: invalid --enforcement: $ENFORCEMENT" >&2; exit 2 ;;
esac

required_check="$(jq -nc \
    --arg ctx "$STATUS_CONTEXT" \
    --arg integ "$INTEGRATION_ID" \
    '{context: $ctx} + (if ($integ | length) > 0 then {integration_id: ($integ | tonumber)} else {} end)')"

bypass_json="[]"
if (( ${#BYPASS_ACTORS[@]} > 0 )); then
    bypass_json="$(printf '%s\n' "${BYPASS_ACTORS[@]}" | jq -sc 'map(fromjson? // .)')"
fi

payload="$(jq -nc \
    --arg name "$RULESET_NAME" \
    --arg target "branch" \
    --arg enforcement "$ENFORCEMENT" \
    --arg ref "refs/heads/${BRANCH}" \
    --argjson required_check "$required_check" \
    --argjson bypass_actors "$bypass_json" \
    '{
        name: $name,
        target: $target,
        enforcement: $enforcement,
        bypass_actors: $bypass_actors,
        conditions: { ref_name: { include: [$ref], exclude: [] } },
        rules: [
            { type: "deletion" },
            { type: "non_fast_forward" },
            {
                type: "required_status_checks",
                parameters: {
                    strict_required_status_checks_policy: false,
                    do_not_enforce_on_create: true,
                    required_status_checks: [ $required_check ]
                }
            }
        ]
    }')"

if [[ -n "$UPDATE_ID" ]]; then
    method="PUT"
    endpoint="repos/${REPO}/rulesets/${UPDATE_ID}"
else
    method="POST"
    endpoint="repos/${REPO}/rulesets"
fi

echo "configure_branch_protection.sh: target = ${REPO} @ ${BRANCH}"
echo "configure_branch_protection.sh: status context = ${STATUS_CONTEXT}"
echo "configure_branch_protection.sh: enforcement = ${ENFORCEMENT}"
echo "configure_branch_protection.sh: ${method} /${endpoint}"
echo "configure_branch_protection.sh: payload:"
echo "$payload" | jq .

if (( APPLY == 0 )); then
    echo "configure_branch_protection.sh: dry-run (pass --apply to write)"
    exit 0
fi

tmp_payload="$(mktemp)"
trap 'rm -f "$tmp_payload"' EXIT
echo "$payload" > "$tmp_payload"

gh api --method "$method" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    --input "$tmp_payload" \
    "/${endpoint}" | jq .
