# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tool curation for OpenAPI specifications.

This module provides safety-focused transformations for OpenAPI specs before
generating MCP tools. It implements a defense-in-depth approach:

1. Allowlist filtering - Only expose explicitly approved operations
2. Read-only by default - Block write operations unless enabled
3. Operation ID aliasing - Rename operations to be LLM-friendly
4. Limit parameter capping - Prevent excessive pagination requests

The goal is to provide a minimal, safe, and usable API surface for LLMs.
"""

from typing import Any, Dict, Set, Tuple, Optional
import json
import logging
import re

from .constants import (
    OPENAPI_KEY_PATHS,
    OPENAPI_KEY_OPERATION_ID,
    OPENAPI_KEY_PARAMETERS,
    OPENAPI_KEY_NAME,
    OPENAPI_KEY_SCHEMA,
    OPENAPI_KEY_MAXIMUM,
    PARAM_NAME_LIMIT,
    PARAM_NAME_LIMIT_CAPITALIZED,
    DEFAULT_MAX_LIMIT,
    HTTP_METHOD_GET,
    WRITE_METHODS,
    VALID_HTTP_METHODS,
)

# Minimal starter allowlist (expand as you add support)
DEFAULT_ALLOWLIST: Set[Tuple[str, str]] = {
    (HTTP_METHOD_GET, "/shells"),
}

# Friendly aliases (optional, but strongly recommended)
OPERATION_ID_ALIASES = {
    "GetAllAssetAdministrationShells": "list_shells",
    # Add more operationIds here...
}


def _matches_allowlist_pattern(method: str, path: str, allowlist: Set[Tuple[str, str]]) -> bool:
    """
    Check if a method/path combination matches any pattern in the allowlist.

    Supports wildcards:
    - (*, path) - All methods for a specific path
    - (method, *) - A specific method for all paths
    - (*, *) - All methods for all paths

    Args:
        method: HTTP method (lowercase, e.g., 'get', 'post')
        path: URL path (e.g., '/shells', '/shells/{aasIdentifier}')
        allowlist: Set of (method, path) tuples, may include wildcards

    Returns:
        True if the method/path matches any allowlist pattern
    """
    # Exact match
    if (method, path) in allowlist:
        return True

    # Wildcard matches
    if ('*', path) in allowlist:  # All methods for this path
        return True

    if (method, '*') in allowlist:  # This method for all paths
        return True

    if ('*', '*') in allowlist:  # All methods for all paths
        return True

    return False


def curate_openapi_spec(
    spec: Dict[str, Any],
    enable_writes: bool,
    curation_settings: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Curate OpenAPI spec for MCP tool generation.

    Applies the following transformations:
    1. Allowlist filtering - only expose specific operations (supports wildcards)
    2. Read-only enforcement - block write operations unless enabled
    3. Operation ID aliasing - rename to LLM-friendly names
    4. Limit parameter capping - prevent excessive pagination

    Wildcard support in allowlist:
    - [*, /shells] - All methods for /shells path
    - [get, *] - GET method for all paths
    - [*, *] - All methods for all paths (use with caution!)

    Args:
        spec: OpenAPI specification dictionary
        enable_writes: Whether to allow write operations (POST/PUT/PATCH/DELETE)
        curation_settings: Optional dict with:
            - 'allowlist': Set of (method, path) tuples to expose (or list of [method, path] lists)
                          Supports wildcards: '*' for method or path
            - 'aliases': Dict mapping operationId -> friendly name
            If None, uses DEFAULT_ALLOWLIST and OPERATION_ID_ALIASES

    Returns:
        Curated OpenAPI specification
    """
    logger = logging.getLogger(__name__)

    logger.info(f"=== Starting curation (enable_writes={enable_writes}) ===")

    # Use custom curation settings or fall back to defaults
    raw_allowlist = (
        curation_settings.get('allowlist', DEFAULT_ALLOWLIST)
        if curation_settings
        else DEFAULT_ALLOWLIST
    )

    # Convert allowlist from YAML format (list of lists) to set of tuples
    if isinstance(raw_allowlist, list):
        allowlist = {tuple(item) for item in raw_allowlist}
        logger.debug(f"Converted allowlist from list to set: {len(allowlist)} entries")
    else:
        allowlist = raw_allowlist

    aliases = (
        curation_settings.get('aliases', OPERATION_ID_ALIASES)
        if curation_settings
        else OPERATION_ID_ALIASES
    )

    out = dict(spec)

    paths = out.get(OPENAPI_KEY_PATHS, {})
    new_paths: Dict[str, Any] = {}

    logger.debug(f"Starting curation with {len(paths)} paths")
    logger.debug(f"Allowlist has {len(allowlist)} entries: {allowlist}")
    logger.debug(f"Write operations enabled: {enable_writes}")

    for path, path_item in paths.items():
        new_item: Dict[str, Any] = {}
        for method, op in (path_item or {}).items():
            m = method.lower()
            if m not in VALID_HTTP_METHODS:
                continue

            # 1) Allowlist filter (keeps tool surface stable, supports wildcards)
            if not _matches_allowlist_pattern(m, path, allowlist):
                logger.debug(f"Filtered out by allowlist: {m.upper()} {path}")
                continue

            # 2) Readonly-by-default safety gate
            if (m in WRITE_METHODS) and not enable_writes:
                logger.debug(f"Filtered out by write protection: {m.upper()} {path}")
                continue

            logger.debug(f"✓ Allowed: {m.upper()} {path}")
            op = dict(op or {})

            # 3) Rename tool via operationId aliasing (LLM-friendly)
            op_id = op.get(OPENAPI_KEY_OPERATION_ID)
            if op_id in aliases:
                op[OPENAPI_KEY_OPERATION_ID] = aliases[op_id]

            # 4) Cap limit parameter (defensive)
            op = _cap_limit_parameter(op, max_limit=DEFAULT_MAX_LIMIT)

            new_item[m] = op

        if new_item:
            new_paths[path] = new_item

    out[OPENAPI_KEY_PATHS] = new_paths
    return out


def _cap_limit_parameter(op: Dict[str, Any], max_limit: int) -> Dict[str, Any]:
    """
    Cap the maximum value of limit parameters in an operation.

    Args:
        op: Operation definition from OpenAPI spec
        max_limit: Maximum allowed value for limit parameters

    Returns:
        Operation with capped limit parameters
    """
    params = op.get(OPENAPI_KEY_PARAMETERS) or []
    new_params = []
    for p in params:
        p2 = dict(p)
        schema = p2.get(OPENAPI_KEY_SCHEMA)
        if isinstance(schema, dict) and p2.get(OPENAPI_KEY_NAME) in {PARAM_NAME_LIMIT, PARAM_NAME_LIMIT_CAPITALIZED}:
            schema = dict(schema)
            schema[OPENAPI_KEY_MAXIMUM] = max_limit
            p2[OPENAPI_KEY_SCHEMA] = schema
        new_params.append(p2)
    op[OPENAPI_KEY_PARAMETERS] = new_params
    return op


# ---------------------------------------------------------------------------
# Schema pruning
# ---------------------------------------------------------------------------

_REF_PATTERN = re.compile(r'"#/components/schemas/([^"]+)"')


def prune_unused_schemas(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove components/schemas entries not reachable from any path in the spec.

    After curation filters the path surface area, many schemas are no longer
    referenced. Leaving them in causes FastMCP's Pydantic validator to process
    circular schemas from unrelated (filtered-out) paths, which hangs or crashes.

    Reachability is seeded from:
    - spec.paths (direct operation $refs)
    - spec.components.responses, requestBodies, parameters, headers, callbacks
      (indirect $refs: a path may reference #/components/responses/X which in
      turn references #/components/schemas/Y — both X and Y are reachable)

    Args:
        spec: Curated OpenAPI specification (paths already filtered).

    Returns:
        New spec dict with only reachable schemas kept. Input is not mutated.
    """
    logger = logging.getLogger(__name__)

    schemas: Dict[str, Any] = spec.get("components", {}).get("schemas", {})
    if not schemas:
        return spec

    components = spec.get("components", {})

    # Seed traversal from paths AND all non-schema component sections.
    # Non-schema components (responses, requestBodies, parameters, headers,
    # callbacks) can contain $refs to schemas; paths may reference them via
    # $ref: '#/components/responses/Foo' etc.
    seed: Dict[str, Any] = {"paths": spec.get("paths", {})}
    for section in ("responses", "requestBodies", "parameters", "headers", "callbacks"):
        if section in components:
            seed[section] = components[section]

    reachable: Set[str] = set()
    _collect_refs(seed, schemas, reachable)

    removed = set(schemas.keys()) - reachable
    if not removed:
        return spec

    logger.debug(
        "Pruning %d unreachable schemas: %s",
        len(removed),
        sorted(removed),
    )

    new_schemas = {k: v for k, v in schemas.items() if k in reachable}
    result = dict(spec)
    result["components"] = dict(spec.get("components", {}))
    result["components"]["schemas"] = new_schemas
    return result


def _collect_refs(
    node: Any,
    schemas: Dict[str, Any],
    reachable: Set[str],
) -> None:
    """
    Walk *node* (any JSON-serialisable value) and collect all
    #/components/schemas/<name> references into *reachable*, then
    recursively walk the schema bodies of newly found names.
    Handles cycles via the reachable set (each name visited at most once).
    """
    # Serialise to JSON string for a simple, recursive-free ref scan
    text = json.dumps(node)
    for name in _REF_PATTERN.findall(text):
        if name not in reachable and name in schemas:
            reachable.add(name)
            # Recurse into the schema body to find transitive refs
            _collect_refs(schemas[name], schemas, reachable)
