# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Shared constants for AAS MCP Server.

This module contains all constant values used across the codebase to avoid duplication.
"""

# ============================================================================
# OpenAPI Spec Structure Keys
# ============================================================================
OPENAPI_KEY_PATHS = "paths"
OPENAPI_KEY_OPERATION_ID = "operationId"
OPENAPI_KEY_PARAMETERS = "parameters"
OPENAPI_KEY_NAME = "name"
OPENAPI_KEY_SCHEMA = "schema"
OPENAPI_KEY_MAXIMUM = "maximum"

# ============================================================================
# HTTP Methods
# ============================================================================
HTTP_METHOD_GET = "get"
HTTP_METHOD_POST = "post"
HTTP_METHOD_PUT = "put"
HTTP_METHOD_PATCH = "patch"
HTTP_METHOD_DELETE = "delete"
HTTP_METHOD_HEAD = "head"
HTTP_METHOD_OPTIONS = "options"
HTTP_METHOD_TRACE = "trace"

# All valid HTTP methods
VALID_HTTP_METHODS = {
    HTTP_METHOD_GET,
    HTTP_METHOD_POST,
    HTTP_METHOD_PUT,
    HTTP_METHOD_PATCH,
    HTTP_METHOD_DELETE,
    HTTP_METHOD_HEAD,
    HTTP_METHOD_OPTIONS,
    HTTP_METHOD_TRACE,
}

# Methods considered "write" operations
WRITE_METHODS = {
    HTTP_METHOD_POST,
    HTTP_METHOD_PUT,
    HTTP_METHOD_PATCH,
    HTTP_METHOD_DELETE,
}

# ============================================================================
# Parameter Names
# ============================================================================
PARAM_NAME_LIMIT = "limit"
PARAM_NAME_LIMIT_CAPITALIZED = "Limit"

# ============================================================================
# Default Values
# ============================================================================
DEFAULT_MAX_LIMIT = 100  # Maximum pagination limit
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_CONFIG_PATH = "/app/config/config.yaml"

# ============================================================================
# Environment Variables
# ============================================================================
ENV_CONFIG_PATH = "CONFIG_PATH"
ENV_LOG_LEVEL = "LOG_LEVEL"
ENV_MCP_TRANSPORT = "MCP_TRANSPORT"
ENV_AAS_BASE_URL = "AAS_BASE_URL"
ENV_AAS_HTTP_TIMEOUT = "AAS_HTTP_TIMEOUT"

# OAuth 2.1 configuration (for HTTP transports)
ENV_OAUTH_ISSUER_URL = "OAUTH_ISSUER_URL"
ENV_OAUTH_CLIENT_ID = "OAUTH_CLIENT_ID"
ENV_OAUTH_CLIENT_SECRET = "OAUTH_CLIENT_SECRET"
ENV_OAUTH_JWT_SIGNING_KEY = "OAUTH_JWT_SIGNING_KEY"
ENV_OAUTH_AUDIENCE = "OAUTH_AUDIENCE"
ENV_OAUTH_REQUIRED_SCOPES = "OAUTH_REQUIRED_SCOPES"
ENV_OAUTH_SERVER_BASE_URL = "OAUTH_SERVER_BASE_URL"
ENV_OAUTH_SESSION_STORE_URL = "OAUTH_SESSION_STORE_URL"
ENV_MCP_RATE_LIMIT_PER_MINUTE = "MCP_RATE_LIMIT_PER_MINUTE"

# Backend token strategy (for AAS API calls)
ENV_BACKEND_AUTH_STRATEGY = "BACKEND_AUTH_STRATEGY"
ENV_BACKEND_AUTH_AUDIENCE = "BACKEND_AUTH_AUDIENCE"
ENV_BACKEND_AUTH_SCOPE = "BACKEND_AUTH_SCOPE"
ENV_BACKEND_AUTH_TOKEN_ENDPOINT = "BACKEND_AUTH_TOKEN_ENDPOINT"
ENV_BACKEND_AUTH_CLIENT_ID = "BACKEND_AUTH_CLIENT_ID"
ENV_BACKEND_AUTH_CLIENT_SECRET = "BACKEND_AUTH_CLIENT_SECRET"

# Strategy names
BACKEND_STRATEGY_FORWARD = "forward"
BACKEND_STRATEGY_TOKEN_EXCHANGE = "token_exchange"
BACKEND_STRATEGY_NONE = "none"
VALID_BACKEND_STRATEGIES = frozenset({
    BACKEND_STRATEGY_FORWARD,
    BACKEND_STRATEGY_TOKEN_EXCHANGE,
    BACKEND_STRATEGY_NONE,
})

# RFC 8693 grant type
OAUTH_GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
OAUTH_TOKEN_TYPE_ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"

# ============================================================================
# Server Configuration
# ============================================================================
SERVER_NAME_FORMAT = "AAS MCP Server ({component_name})"
DEFAULT_HTTP_TIMEOUT = 30  # seconds
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
SECONDS_PER_MINUTE = 60

# OAuth / auth configuration
LOCALHOST_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost"})
# Wildcard bind addresses — not client-reachable and must not be advertised
# in OAuth resource metadata without an explicit OAUTH_SERVER_BASE_URL override.
WILDCARD_BIND_ADDRESSES = frozenset({"0.0.0.0", "::"})

# ============================================================================
# Path and Filter Delimiters (for openapi_loader)
# ============================================================================
FILTER_DELIMITER = ":"
METHOD_SEPARATOR = ","
PATH_FILTER_SEPARATOR = ";"

# ============================================================================
# File Configuration
# ============================================================================
FILE_ENCODING = "utf-8"
OVERLAY_FILE_PATTERN = "{component_name}-overlay.yaml"

# ============================================================================
# Component Filter Environment Variables
# ============================================================================
COMPONENT_FILTER_ENV_VARS = {
    "aas-repo": "AAS_REPO_FILTER_PATHS",
    "submodel-repo": "SUBMODEL_REPO_FILTER_PATHS",
    "aas-registry": "AAS_REGISTRY_FILTER_PATHS",
    "submodel-registry": "SUBMODEL_REGISTRY_FILTER_PATHS",
}
