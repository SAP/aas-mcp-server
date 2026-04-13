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

from typing import Any, Dict, Set, Tuple

# OpenAPI spec structure keys
OPENAPI_KEY_PATHS = "paths"
OPENAPI_KEY_OPERATION_ID = "operationId"
OPENAPI_KEY_PARAMETERS = "parameters"
OPENAPI_KEY_NAME = "name"
OPENAPI_KEY_SCHEMA = "schema"
OPENAPI_KEY_MAXIMUM = "maximum"

# Parameter names for limit capping
PARAM_NAME_LIMIT = "limit"
PARAM_NAME_LIMIT_CAPITALIZED = "Limit"

# Default maximum limit for pagination
DEFAULT_MAX_LIMIT = 100

# HTTP methods
HTTP_METHOD_GET = "get"
HTTP_METHOD_POST = "post"
HTTP_METHOD_PUT = "put"
HTTP_METHOD_PATCH = "patch"
HTTP_METHOD_DELETE = "delete"

# Minimal starter allowlist (expand as you add support)
DEFAULT_ALLOWLIST: Set[Tuple[str, str]] = {
    (HTTP_METHOD_GET, "/shells"),
    # (HTTP_METHOD_GET, "/shells/{aasIdentifier}"),  # example if present in your spec
}

# operations considered "writes"
WRITE_METHODS = {HTTP_METHOD_POST, HTTP_METHOD_PUT, HTTP_METHOD_PATCH, HTTP_METHOD_DELETE}

VALID_METHODS: Set[str] = {HTTP_METHOD_GET, HTTP_METHOD_POST, HTTP_METHOD_PUT, HTTP_METHOD_PATCH, HTTP_METHOD_DELETE}

# Friendly aliases (optional, but strongly recommended)
OPERATION_ID_ALIASES = {
    "GetAllAssetAdministrationShells": "list_shells",
    # Add more operationIds here...
}


def curate_openapi_spec(spec: Dict[str, Any], enable_writes: bool) -> Dict[str, Any]:
    """
    Curate OpenAPI spec for MCP tool generation.

    Applies the following transformations:
    1. Allowlist filtering - only expose specific operations
    2. Read-only enforcement - block write operations unless enabled
    3. Operation ID aliasing - rename to LLM-friendly names
    4. Limit parameter capping - prevent excessive pagination

    Args:
        spec: OpenAPI specification dictionary
        enable_writes: Whether to allow write operations (POST/PUT/PATCH/DELETE)

    Returns:
        Curated OpenAPI specification
    """
    out = dict(spec)

    paths = out.get(OPENAPI_KEY_PATHS, {})
    new_paths: Dict[str, Any] = {}

    for path, path_item in paths.items():
        new_item: Dict[str, Any] = {}
        for method, op in (path_item or {}).items():
            m = method.lower()
            if m not in VALID_METHODS:
                continue

            # 1) Allowlist filter (keeps tool surface stable)
            if (m, path) not in DEFAULT_ALLOWLIST:
                continue

            # 2) Readonly-by-default safety gate
            if (m in WRITE_METHODS) and not enable_writes:
                continue

            op = dict(op or {})

            # 3) Rename tool via operationId aliasing (LLM-friendly)
            op_id = op.get(OPENAPI_KEY_OPERATION_ID)
            if op_id in OPERATION_ID_ALIASES:
                op[OPENAPI_KEY_OPERATION_ID] = OPERATION_ID_ALIASES[op_id]

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
