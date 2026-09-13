#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0
#
# docker-startup-check.sh — Two-part startup check for the aas-mcp-server
# Docker image. Verifies that a given AAS component:
#   1. Responds correctly to an MCP `initialize` handshake (handshake phase).
#   2. Stays running for UPTIME_SECONDS without exiting non-zero (uptime phase).
#
# Used by the CI `integration-test` matrix job and runnable locally.

set -euo pipefail

# ---------------------------------------------------------------- usage --

usage() {
  cat <<EOF
Usage: $0 <component> <config-host-path> <spec-host-path>

Runs a two-part Docker startup check for one AAS MCP component.

Arguments:
  <component>          One of: aas-repo, submodel-repo, aas-registry, submodel-registry
  <config-host-path>   Host path to the config.yaml the container should load
  <spec-host-path>     Host path to the OpenAPI spec that config.yaml references

Environment variables:
  UPTIME_SECONDS   Seconds to wait during the uptime phase (default: 10)
  IMAGE_TAG        Docker image tag to use (default: aas-mcp-server:test)

Example:
  $0 aas-repo \\
    tests/fixtures/integration/config.yaml.template \\
    tests/fixtures/integration/aas-repo-official-spec.yaml
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 3 ]]; then
  echo "ERROR: expected 3 positional arguments, got $#" >&2
  usage >&2
  exit 2
fi

COMPONENT="$1"
CONFIG_PATH="$2"
SPEC_PATH="$3"

UPTIME_SECONDS="${UPTIME_SECONDS:-10}"
IMAGE_TAG="${IMAGE_TAG:-aas-mcp-server:test}"

# ---------------------------------------------------------------- setup --

# Resolve to absolute paths so `docker run -v` works regardless of the caller's cwd.
CONFIG_PATH="$(cd "$(dirname "$CONFIG_PATH")" && pwd)/$(basename "$CONFIG_PATH")"
SPEC_PATH="$(cd "$(dirname "$SPEC_PATH")" && pwd)/$(basename "$SPEC_PATH")"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "ERROR: config file not found: $CONFIG_PATH" >&2
  exit 2
fi
if [[ ! -f "$SPEC_PATH" ]]; then
  echo "ERROR: spec file not found: $SPEC_PATH" >&2
  exit 2
fi

# The config file validates EVERY component's official_spec eagerly on load,
# so mounting only the selected component's spec fails validation for the other
# three components declared in the same config.yaml. We therefore mount the
# whole directory containing <SPEC_PATH> at /app/spec/ so all four fixture
# specs are visible to the container. <SPEC_PATH> itself is asserted to exist
# for early-fail behaviour; the container reads it via /app/spec/<basename>.
SPEC_DIR="$(dirname "$SPEC_PATH")"
# Arrays so paths containing spaces don't word-split when expanded into `docker run`.
MOUNT_ARGS=(
  -v "${CONFIG_PATH}:/app/config/config.yaml:ro"
  -v "${SPEC_DIR}:/app/spec:ro"
)

ENV_ARGS=(
  -e "AAS_COMPONENT=${COMPONENT}"
  -e "AAS_BASE_URL=http://localhost:8081"
)

# Private temp dir for state (uptime cidfile, handshake stderr).
# `mktemp -d` avoids the TOCTOU window of `mktemp -u` (which returns a name
# without creating the file). Docker's `--cidfile` requires that the target
# path does NOT exist yet, hence we put the cidfile *inside* the dir.
STATE_DIR="$(mktemp -d)"
UPTIME_CIDFILE="${STATE_DIR}/container.cid"
HANDSHAKE_LOG="${STATE_DIR}/handshake.stderr"

# Cleanup takes an explicit exit code because `trap '... ; cleanup' EXIT` would
# otherwise clobber $? with the exit code of the last command in the trap.
cleanup() {
  local rc="${1:-$?}"
  if [[ -f "$UPTIME_CIDFILE" ]]; then
    local cid
    cid="$(cat "$UPTIME_CIDFILE" 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
      docker stop --time 2 "$cid" >/dev/null 2>&1 || true
      docker rm -f "$cid"        >/dev/null 2>&1 || true
    fi
  fi
  rm -rf "$STATE_DIR"
  exit "$rc"
}
trap 'rc=$?; cleanup "$rc"' EXIT INT TERM

echo "=== docker-startup-check: component=${COMPONENT} image=${IMAGE_TAG} uptime=${UPTIME_SECONDS}s ==="

# ---------------------------------------------------- phase 1: handshake --

echo "--- Phase 1/2: MCP initialize + tools/list ---"

EXPECTED_NAME="AAS MCP Server (${COMPONENT})"
# Two JSON-RPC requests, newline-delimited: initialize then tools/list.
# tools/list also gates on curation+spec having produced ≥1 tool, so a
# mis-parsed allowlist (which would still pass a name-only check) fails here.
INIT_REQUEST='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"docker-startup-check","version":"1.0"}}}'
TOOLS_REQUEST='{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

set +e
HANDSHAKE_STDOUT="$(
  printf '%s\n%s\n' "$INIT_REQUEST" "$TOOLS_REQUEST" \
    | docker run --rm -i \
        "${MOUNT_ARGS[@]}" "${ENV_ARGS[@]}" \
        "$IMAGE_TAG" \
        2> "$HANDSHAKE_LOG"
)"
HANDSHAKE_RC=$?
set -e

# stdio MCP is line-delimited JSON; match responses by id.
INIT_LINE="$(echo "$HANDSHAKE_STDOUT"   | jq -c 'select(.id==1)' 2>/dev/null | head -n1)"
TOOLS_LINE="$(echo "$HANDSHAKE_STDOUT"  | jq -c 'select(.id==2)' 2>/dev/null | head -n1)"

if [[ "$HANDSHAKE_RC" -ne 0 ]] || [[ -z "$INIT_LINE" ]] || [[ -z "$TOOLS_LINE" ]]; then
  echo "ERROR: handshake container exited with rc=$HANDSHAKE_RC or missing id=1/id=2 response" >&2
  echo "--- container stderr ---" >&2
  cat "$HANDSHAKE_LOG" >&2 || true
  echo "--- container stdout ---" >&2
  echo "$HANDSHAKE_STDOUT" >&2
  exit 1
fi

if ! echo "$INIT_LINE" | jq -e --arg name "$EXPECTED_NAME" '.result.serverInfo.name == $name' >/dev/null; then
  echo "ERROR: initialize response did not match expected serverInfo.name=\"$EXPECTED_NAME\"" >&2
  echo "--- response line ---" >&2
  echo "$INIT_LINE" >&2
  echo "--- container stderr ---" >&2
  cat "$HANDSHAKE_LOG" >&2 || true
  exit 1
fi

if ! echo "$TOOLS_LINE" | jq -e '.result.tools | length > 0' >/dev/null; then
  TOOL_COUNT="$(echo "$TOOLS_LINE" | jq -r '.result.tools | length' 2>/dev/null || echo "?")"
  echo "ERROR: tools/list returned $TOOL_COUNT tools (expected ≥1); spec + curation loaded nothing" >&2
  echo "--- response line ---" >&2
  echo "$TOOLS_LINE" >&2
  echo "--- container stderr ---" >&2
  cat "$HANDSHAKE_LOG" >&2 || true
  exit 1
fi

TOOL_COUNT="$(echo "$TOOLS_LINE" | jq -r '.result.tools | length')"
echo "OK: serverInfo.name == \"$EXPECTED_NAME\", tools/list returned $TOOL_COUNT tools"

# ------------------------------------------------------ phase 2: uptime --

echo "--- Phase 2/2: uptime check (${UPTIME_SECONDS}s) ---"

# `-i` keeps stdin attached; the server blocks on stdin.readline() and will not
# exit on its own. `-d` detaches so we can inspect it after N seconds.
docker run -d -i \
  --cidfile "$UPTIME_CIDFILE" \
  "${MOUNT_ARGS[@]}" "${ENV_ARGS[@]}" \
  "$IMAGE_TAG" \
  >/dev/null

CID="$(cat "$UPTIME_CIDFILE")"
echo "detached container: $CID"

sleep "$UPTIME_SECONDS"

STATE_RUNNING="$(docker inspect --format '{{.State.Running}}' "$CID" 2>/dev/null || echo "unknown")"
STATE_EXITCODE="$(docker inspect --format '{{.State.ExitCode}}' "$CID" 2>/dev/null || echo "unknown")"

if [[ "$STATE_RUNNING" != "true" ]] || [[ "$STATE_EXITCODE" != "0" ]]; then
  echo "ERROR: uptime check failed after ${UPTIME_SECONDS}s" >&2
  echo "  State.Running  = $STATE_RUNNING (expected: true)" >&2
  echo "  State.ExitCode = $STATE_EXITCODE (expected: 0)" >&2
  echo "--- container logs ---" >&2
  docker logs "$CID" >&2 2>&1 || true
  exit 1
fi

echo "OK: container is still running with exit code 0 after ${UPTIME_SECONDS}s"

# `trap cleanup EXIT` handles docker stop/rm on the way out.
echo "=== docker-startup-check: PASS (component=${COMPONENT}) ==="
