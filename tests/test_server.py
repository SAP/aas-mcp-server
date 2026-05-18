# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for server module.

Tests the MCP server builder orchestration.
"""

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastmcp.server.auth import JWTVerifier, RemoteAuthProvider
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

from aas_mcp_server.server import (
    build_mcp_server,
    build_jwt_verifier,
    build_auth_provider,
)
from aas_mcp_server.constants import DEFAULT_LOG_LEVEL, SERVER_NAME_FORMAT
from aas_mcp_server.config import ComponentConfig


# ---------------------------------------------------------------------------
# Module-level test constants
# ---------------------------------------------------------------------------

# An empty OpenAPI spec used as a return value when mocking the pipeline
EMPTY_SPEC = {"paths": {}}

# OAuth test values (no real network calls — only used in env-var patches)
TEST_ISSUER_URL = "https://idp.example.com/realms/test"
TEST_AUDIENCE = "aas-mcp-server"
TEST_JWKS_URI_CUSTOM = "https://idp.example.com/custom/jwks"
TEST_JWKS_URI_DERIVED = f"{TEST_ISSUER_URL}/.well-known/jwks.json"


# ---------------------------------------------------------------------------
# Shared mock factory (replaces two near-identical per-class helpers)
# ---------------------------------------------------------------------------

def make_mock_component(name: str = "aas-repo") -> MagicMock:
    """Return a MagicMock that satisfies the ComponentConfig interface."""
    m = MagicMock(spec=ComponentConfig)
    m.component_name = name
    m.curation = None
    m.official_spec = Path("/app/specs/official.yaml")
    m.implementation_spec = None
    m.overlay = None
    m.has_both_specs.return_value = False
    return m


class TestBuildMcpServer:
    """Tests for build_mcp_server function."""

    @staticmethod
    def _create_mock_component_config(component_name="aas-repo"):
        return make_mock_component(component_name)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_calls_configure_logging_with_provided_level(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that configure_logging is called with provided log level."""
        mock_process_spec.return_value = EMPTY_SPEC
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
            log_level="DEBUG",
        )

        mock_configure_logging.assert_called_once_with("DEBUG", transport="stdio")

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_calls_configure_logging_with_default_level(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that configure_logging uses default log level when not provided."""
        mock_process_spec.return_value = EMPTY_SPEC
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_configure_logging.assert_called_once_with(DEFAULT_LOG_LEVEL, transport="stdio")

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_processes_component_spec(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that process_component_spec is called with component config."""
        mock_spec = EMPTY_SPEC
        mock_process_spec.return_value = mock_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_process_spec.assert_called_once_with(mock_component_config)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_curates_spec_with_enable_writes_false(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that curate_openapi_spec is called with enable_writes=False."""
        mock_spec = EMPTY_SPEC
        flat_spec = EMPTY_SPEC
        mock_process_spec.return_value = mock_spec
        mock_flatten.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_curate.assert_called_once_with(flat_spec, enable_writes=False, curation_settings=None)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_curates_spec_with_enable_writes_true(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that curate_openapi_spec is called with enable_writes=True."""
        mock_spec = EMPTY_SPEC
        flat_spec = EMPTY_SPEC
        mock_process_spec.return_value = mock_spec
        mock_flatten.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=True,
        )

        mock_curate.assert_called_once_with(flat_spec, enable_writes=True, curation_settings=None)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_curates_spec_with_curation_settings(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that curate_openapi_spec is called with curation settings from config."""
        mock_spec = EMPTY_SPEC
        flat_spec = EMPTY_SPEC
        mock_process_spec.return_value = mock_spec
        mock_flatten.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()
        mock_curation_settings = {"allowlist": [("get", "/shells")]}
        mock_component_config.curation = mock_curation_settings

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_curate.assert_called_once_with(flat_spec, enable_writes=False, curation_settings=mock_curation_settings)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_builds_http_client_with_base_url(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that build_async_client is called with correct base_url."""
        mock_process_spec.return_value = EMPTY_SPEC
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://prod-server:9000",
            enable_writes=False,
        )

        mock_build_client.assert_called_once_with(base_url="http://prod-server:9000")

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_creates_fastmcp_server_with_curated_spec(
        self,
        mock_fastmcp_class,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that FastMCP.from_openapi is called with pruned curated spec."""
        mock_spec = EMPTY_SPEC
        mock_curated_spec = {"paths": {"/shells": {}}}
        mock_pruned_spec = {"paths": {"/shells": {}}, "components": {"schemas": {}}}
        mock_process_spec.return_value = mock_spec
        mock_curate.return_value = mock_curated_spec
        mock_prune.return_value = mock_pruned_spec
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_component_config = self._create_mock_component_config("aas-repo")

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_fastmcp_class.from_openapi.assert_called_once_with(
            openapi_spec=mock_pruned_spec,
            client=mock_client,
            name=SERVER_NAME_FORMAT.format(component_name="aas-repo"),
            auth=None,
            middleware=mock_fastmcp_class.from_openapi.call_args.kwargs["middleware"],
        )

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_returns_fastmcp_instance(
        self,
        mock_fastmcp_class,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that build_mcp_server returns a FastMCP instance."""
        mock_process_spec.return_value = EMPTY_SPEC
        mock_mcp_instance = MagicMock()
        mock_fastmcp_class.from_openapi.return_value = mock_mcp_instance
        mock_component_config = self._create_mock_component_config()

        result = build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        assert result == mock_mcp_instance

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_flattens_spec_before_curation(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """flatten_spec_schemas is called on the raw spec, and curation receives the flattened result."""
        raw_spec = {"paths": {}, "components": {"schemas": {"Shell": {"allOf": []}}}}
        flat_spec = {"paths": {}, "components": {"schemas": {"Shell": {"type": "object"}}}}
        mock_process_spec.return_value = raw_spec
        mock_flatten.return_value = flat_spec
        mock_prune.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_flatten.assert_called_once_with(raw_spec)
        # curate receives the flattened spec
        args, kwargs = mock_curate.call_args
        assert args[0] is flat_spec or kwargs.get("spec") is flat_spec

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_prunes_schemas_after_curation(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """prune_unused_schemas is called on the curated spec, and FastMCP receives the pruned result."""
        raw_spec = EMPTY_SPEC
        curated_spec = {"paths": {"/shells": {}}, "components": {"schemas": {"Shell": {}, "Orphan": {}}}}
        pruned_spec = {"paths": {"/shells": {}}, "components": {"schemas": {"Shell": {}}}}
        mock_process_spec.return_value = raw_spec
        mock_flatten.return_value = raw_spec
        mock_curate.return_value = curated_spec
        mock_prune.return_value = pruned_spec
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_component_config = self._create_mock_component_config("aas-repo")

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_prune.assert_called_once_with(curated_spec)
        call_kwargs = mock_fastmcp.from_openapi.call_args.kwargs
        assert call_kwargs["openapi_spec"] == pruned_spec
        assert call_kwargs["client"] == mock_client
        assert call_kwargs["name"] == SERVER_NAME_FORMAT.format(component_name="aas-repo")

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_pipeline_execution_order(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Pipeline steps execute in correct order: load → flatten → curate → prune → client → FastMCP."""
        call_order = []
        mock_component_config = self._create_mock_component_config()

        mock_configure_logging.side_effect = lambda *a, **kw: call_order.append("configure_logging")
        mock_process_spec.side_effect = lambda *a: (call_order.append("process_spec"), EMPTY_SPEC)[1]
        mock_flatten.side_effect = lambda *a: (call_order.append("flatten"), EMPTY_SPEC)[1]
        mock_curate.side_effect = lambda *a, **kw: (call_order.append("curate"), EMPTY_SPEC)[1]
        mock_prune.side_effect = lambda *a: (call_order.append("prune"), EMPTY_SPEC)[1]
        mock_build_client.side_effect = lambda **kw: (call_order.append("build_client"), MagicMock())[1]
        mock_fastmcp.from_openapi.side_effect = lambda **kw: (call_order.append("fastmcp"), MagicMock())[1]

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        assert call_order == [
            "configure_logging",
            "process_spec",
            "flatten",
            "curate",
            "prune",
            "build_client",
            "fastmcp",
        ]


class TestConstants:
    """Tests for module constants."""

    def test_default_log_level_is_info(self):
        """Test that default log level is INFO."""
        assert DEFAULT_LOG_LEVEL == "INFO"

    def test_server_name_format_has_placeholder(self):
        """Test that server name format has component_name placeholder."""
        assert "{component_name}" in SERVER_NAME_FORMAT

    def test_server_name_format_produces_correct_name(self):
        """Test that server name format produces expected string."""
        result = SERVER_NAME_FORMAT.format(component_name="test-component")
        assert "AAS MCP Server" in result
        assert "test-component" in result


class TestBuildJwtVerifier:
    """Tests for build_jwt_verifier function — task 3.6."""

    @patch.dict(os.environ, {}, clear=True)
    def test_returns_none_when_oauth_issuer_not_set(self):
        """No OAUTH_ISSUER_URL means no auth (current default behaviour)."""
        result = build_jwt_verifier()
        assert result is None

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
    })
    def test_returns_jwt_verifier_when_issuer_is_set(self):
        """OAUTH_ISSUER_URL set → returns a JWTVerifier instance."""
        result = build_jwt_verifier()
        assert isinstance(result, JWTVerifier)

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
    })
    def test_jwks_uri_derived_from_issuer_when_not_set(self):
        """JWKS URI defaults to {issuer}/.well-known/jwks.json."""
        result = build_jwt_verifier()
        assert result is not None
        assert result.jwks_uri == TEST_JWKS_URI_DERIVED

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
        "OAUTH_JWKS_URI": TEST_JWKS_URI_CUSTOM,
    })
    def test_explicit_jwks_uri_overrides_default(self):
        """OAUTH_JWKS_URI override is respected."""
        result = build_jwt_verifier()
        assert result is not None
        assert result.jwks_uri == TEST_JWKS_URI_CUSTOM

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
        "OAUTH_REQUIRED_SCOPES": "aas:read,aas:write",
    })
    def test_required_scopes_parsed_from_env(self):
        """Comma-separated OAUTH_REQUIRED_SCOPES are parsed into a list."""
        result = build_jwt_verifier()
        assert result is not None
        assert result.required_scopes is not None
        assert "aas:read" in result.required_scopes
        assert "aas:write" in result.required_scopes

    @patch.dict(os.environ, {"OAUTH_ISSUER_URL": TEST_ISSUER_URL})
    def test_warning_emitted_when_audience_not_set(self, caplog):
        """Missing OAUTH_AUDIENCE triggers a security WARNING (GAP-1)."""
        with caplog.at_level(logging.WARNING, logger="aas_mcp_server.server"):
            build_jwt_verifier()
        assert any("OAUTH_AUDIENCE" in r.message for r in caplog.records)
        assert any(
            "audience" in r.message.lower() for r in caplog.records
        )


class TestBuildMcpServerAuth:
    """Tests that build_mcp_server wires auth and rate limiting."""

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.flatten_spec_schemas", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.curate_openapi_spec", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.prune_unused_schemas", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    @patch.dict(os.environ, {}, clear=True)
    def test_auth_is_none_when_oauth_not_configured(
        self, mock_fastmcp, mock_client, *args
    ):
        """auth=None is passed to FastMCP when OAUTH_ISSUER_URL is not set."""
        build_mcp_server(make_mock_component(), "http://localhost", False)
        _, kwargs = mock_fastmcp.from_openapi.call_args
        assert kwargs.get("auth") is None

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.flatten_spec_schemas", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.curate_openapi_spec", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.prune_unused_schemas", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
    })
    def test_remote_auth_provider_passed_when_oauth_configured(
        self, mock_fastmcp, mock_client, *args
    ):
        """RemoteAuthProvider is passed as auth= when OAUTH_ISSUER_URL is set.

        RemoteAuthProvider wraps JWTVerifier and also serves the RFC 9728
        protected resource metadata endpoint so MCP clients can discover
        the authorization server automatically.
        """
        build_mcp_server(make_mock_component(), "http://localhost", False)
        _, kwargs = mock_fastmcp.from_openapi.call_args
        assert isinstance(kwargs.get("auth"), RemoteAuthProvider)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.flatten_spec_schemas", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.curate_openapi_spec", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.prune_unused_schemas", return_value=EMPTY_SPEC)
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    @patch.dict(os.environ, {}, clear=True)
    def test_rate_limiter_always_present(self, mock_fastmcp, mock_client, *args):
        """RateLimitingMiddleware is always included in middleware list."""
        build_mcp_server(make_mock_component(), "http://localhost", False)
        _, kwargs = mock_fastmcp.from_openapi.call_args
        middleware = kwargs.get("middleware", [])
        assert any(isinstance(m, RateLimitingMiddleware) for m in middleware)


class TestBuildAuthProvider:
    """Tests for build_auth_provider — the RemoteAuthProvider wrapper."""

    @patch.dict(os.environ, {}, clear=True)
    def test_returns_none_when_issuer_not_set(self):
        """No OAUTH_ISSUER_URL → no auth provider."""
        assert build_auth_provider(host="127.0.0.1", port=8000) is None

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
    })
    def test_returns_remote_auth_provider(self):
        """Returns a RemoteAuthProvider when OAUTH_ISSUER_URL is set."""
        result = build_auth_provider(host="127.0.0.1", port=8000)
        assert isinstance(result, RemoteAuthProvider)

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
    })
    def test_authorization_server_set_to_issuer(self):
        """RemoteAuthProvider advertises the issuer as the authorization server."""
        result = build_auth_provider(host="127.0.0.1", port=8000)
        assert result is not None
        assert any(
            TEST_ISSUER_URL in str(s) for s in result.authorization_servers
        )

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
    })
    def test_base_url_constructed_from_host_port(self):
        """base_url is constructed from host and port when not explicitly set."""
        result = build_auth_provider(host="127.0.0.1", port=8000)
        assert result is not None
        assert "127.0.0.1" in str(result.base_url)
        assert "8000" in str(result.base_url)

    @patch.dict(os.environ, {
        "OAUTH_ISSUER_URL": TEST_ISSUER_URL,
        "OAUTH_AUDIENCE": TEST_AUDIENCE,
        "OAUTH_SERVER_BASE_URL": "https://mcp.example.com",
    })
    def test_explicit_base_url_overrides_host_port(self):
        """OAUTH_SERVER_BASE_URL override is respected (reverse-proxy case)."""
        result = build_auth_provider(host="127.0.0.1", port=8000)
        assert result is not None
        assert "mcp.example.com" in str(result.base_url)
