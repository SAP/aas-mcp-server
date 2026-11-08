#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0
#
# update-integration-fixtures.sh — Regenerates tests/fixtures/integration/*-official-spec.yaml
# from a git tag of https://github.com/admin-shell-io/aas-specs-api.
#
# For each component, the SSP-001 spec of the tag is bundled into one
# self-contained file (the same steps as README "Setup"):
#   1. shallow-clone the tag
#   2. point the SwaggerHub schema refs (v3.1.x) at the Part1/Part2 files of
#      the same tag (no-op for v3.2.0, which references local files already)
#   3. `redocly bundle` moves all external $refs into `components`
#
# Usage: scripts/ci/update-integration-fixtures.sh [<tag>]   (default: v3.1.3)
# Needs git, perl and npx (Node.js). Works with bash 3.2 (macOS).

set -euo pipefail

TAG="${1:-v3.1.3}"
REDOCLY="@redocly/cli@1.25.0"
REPO_URL="https://github.com/admin-shell-io/aas-specs-api"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${ROOT}/tests/fixtures/integration"

# v3.1.3 -> V3.1 (the spec file names carry the minor version only)
MINOR="$(echo "$TAG" | sed -E 's/^v([0-9]+\.[0-9]+).*/V\1/')"

# <component>:<service folder in aas-specs-api>
COMPONENTS="
aas-repo:AssetAdministrationShellRepositoryServiceSpecification
submodel-repo:SubmodelRepositoryServiceSpecification
aas-registry:AssetAdministrationShellRegistryServiceSpecification
submodel-registry:SubmodelRegistryServiceSpecification
concept-description-repo:ConceptDescriptionRepositoryServiceSpecification
"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Cloning ${REPO_URL} at ${TAG}"
git clone -q --depth 1 --branch "$TAG" "$REPO_URL" "$TMP/src" 2>/dev/null

find "$TMP/src" -name '*.yaml' -exec perl -pi -e \
  's#https://api\.swaggerhub\.com/domains/Plattform_i40/(Part1-MetaModel-Schemas|Part2-API-Schemas)/V[0-9.]+#../$1/openapi.yaml#g' {} +

for entry in $COMPONENTS; do
  component="${entry%%:*}"
  service="${entry#*:}"
  src="$TMP/src/${service}/${MINOR}_SSP-001.yaml"
  out="${OUT_DIR}/${component}-official-spec.yaml"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: ${service}/${MINOR}_SSP-001.yaml not found in ${TAG}" >&2
    exit 1
  fi
  npx -y "$REDOCLY" bundle "$src" -o "$out" >/dev/null 2>&1
  if grep -qE "\\\$ref: ['\"]?[^#'\" ]" "$out"; then
    echo "ERROR: ${out} still has external \$refs" >&2
    exit 1
  fi
  echo "  ${component}: ${service}/${MINOR}_SSP-001.yaml -> $(basename "$out")"
done
