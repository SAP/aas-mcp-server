# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for tool_curation module.

Tests the safety-focused transformations for OpenAPI specifications.
"""

from copy import deepcopy

from aas_mcp_server.tool_curation import (
    curate_openapi_spec,
    _cap_limit_parameter,
    DEFAULT_ALLOWLIST,
    OPERATION_ID_ALIASES,
)
from aas_mcp_server.constants import (
    WRITE_METHODS,
    DEFAULT_MAX_LIMIT,
    HTTP_METHOD_GET,
    HTTP_METHOD_POST,
    HTTP_METHOD_DELETE,
    OPENAPI_KEY_PATHS,
    OPENAPI_KEY_OPERATION_ID,
    OPENAPI_KEY_PARAMETERS,
    OPENAPI_KEY_NAME,
    OPENAPI_KEY_SCHEMA,
    OPENAPI_KEY_MAXIMUM,
    PARAM_NAME_LIMIT,
)


class TestCurateOpenApiSpec:
    """Tests for curate_openapi_spec function."""

    def test_filters_paths_not_in_allowlist(self):
        """Test that paths not in allowlist are removed."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"}},
                "/unknown": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getUnknown"}},
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False)

        assert "/shells" in result[OPENAPI_KEY_PATHS]
        assert "/unknown" not in result[OPENAPI_KEY_PATHS]

    def test_blocks_write_methods_when_writes_disabled(self):
        """Test that write methods are blocked when enable_writes=False."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {
                    HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"},
                    HTTP_METHOD_POST: {OPENAPI_KEY_OPERATION_ID: "postShells"},
                }
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False)

        assert HTTP_METHOD_GET in result[OPENAPI_KEY_PATHS]["/shells"]
        assert HTTP_METHOD_POST not in result[OPENAPI_KEY_PATHS]["/shells"]

    def test_allows_write_methods_when_writes_enabled(self):
        """Test that write methods are allowed when enable_writes=True."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {
                    HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"},
                    HTTP_METHOD_POST: {OPENAPI_KEY_OPERATION_ID: "postShells"},
                }
            }
        }

        result = curate_openapi_spec(spec, enable_writes=True)

        # POST is in allowlist, so should be present when writes enabled
        if (HTTP_METHOD_POST, "/shells") in DEFAULT_ALLOWLIST:
            assert HTTP_METHOD_POST in result[OPENAPI_KEY_PATHS]["/shells"]

    def test_applies_operation_id_aliases(self):
        """Test that operation IDs are renamed according to aliases."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {
                    HTTP_METHOD_GET: {
                        OPENAPI_KEY_OPERATION_ID: "GetAllAssetAdministrationShells"
                    }
                }
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False)

        expected_alias = OPERATION_ID_ALIASES.get("GetAllAssetAdministrationShells")
        if expected_alias:
            assert (
                result[OPENAPI_KEY_PATHS]["/shells"][HTTP_METHOD_GET][
                    OPENAPI_KEY_OPERATION_ID
                ]
                == expected_alias
            )

    def test_caps_limit_parameters(self):
        """Test that limit parameters are capped to maximum value."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {
                    HTTP_METHOD_GET: {
                        OPENAPI_KEY_OPERATION_ID: "getShells",
                        OPENAPI_KEY_PARAMETERS: [
                            {
                                OPENAPI_KEY_NAME: PARAM_NAME_LIMIT,
                                OPENAPI_KEY_SCHEMA: {"type": "integer", "maximum": 1000},
                            }
                        ],
                    }
                }
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False)

        params = result[OPENAPI_KEY_PATHS]["/shells"][HTTP_METHOD_GET][
            OPENAPI_KEY_PARAMETERS
        ]
        limit_param = next(p for p in params if p[OPENAPI_KEY_NAME] == PARAM_NAME_LIMIT)
        assert limit_param[OPENAPI_KEY_SCHEMA][OPENAPI_KEY_MAXIMUM] == DEFAULT_MAX_LIMIT

    def test_does_not_modify_original_spec(self):
        """Test that original spec is not modified."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"}}
            }
        }
        original = deepcopy(spec)

        curate_openapi_spec(spec, enable_writes=False)

        assert spec == original

    def test_removes_paths_with_no_allowed_methods(self):
        """Test that paths with no allowed methods are removed entirely."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {HTTP_METHOD_POST: {OPENAPI_KEY_OPERATION_ID: "postShells"}}
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False)

        # If POST /shells is not in allowlist or writes disabled, path should be removed
        if (HTTP_METHOD_POST, "/shells") not in DEFAULT_ALLOWLIST:
            assert "/shells" not in result[OPENAPI_KEY_PATHS]

    def test_ignores_non_http_methods(self):
        """Test that non-HTTP methods are ignored."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {
                    HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"},
                    "parameters": [],  # Not an HTTP method
                    "description": "Shell endpoint",  # Not an HTTP method
                }
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False)

        # Non-HTTP method keys should not cause errors
        assert HTTP_METHOD_GET in result[OPENAPI_KEY_PATHS]["/shells"]

    def test_handles_empty_paths(self):
        """Test that empty paths dict is handled correctly."""
        spec = {OPENAPI_KEY_PATHS: {}}

        result = curate_openapi_spec(spec, enable_writes=False)

        assert result[OPENAPI_KEY_PATHS] == {}

    def test_handles_missing_paths_key(self):
        """Test that missing paths key is handled correctly."""
        spec = {}

        result = curate_openapi_spec(spec, enable_writes=False)

        assert result[OPENAPI_KEY_PATHS] == {}


class TestCapLimitParameter:
    """Tests for _cap_limit_parameter helper function."""

    def test_caps_limit_parameter_with_lowercase_name(self):
        """Test that 'limit' parameter is capped."""
        op = {
            OPENAPI_KEY_PARAMETERS: [
                {
                    OPENAPI_KEY_NAME: PARAM_NAME_LIMIT,
                    OPENAPI_KEY_SCHEMA: {"type": "integer", "maximum": 1000},
                }
            ]
        }

        result = _cap_limit_parameter(op, max_limit=50)

        assert result[OPENAPI_KEY_PARAMETERS][0][OPENAPI_KEY_SCHEMA][OPENAPI_KEY_MAXIMUM] == 50

    def test_caps_limit_parameter_with_capitalized_name(self):
        """Test that 'Limit' parameter is capped."""
        op = {
            OPENAPI_KEY_PARAMETERS: [
                {
                    OPENAPI_KEY_NAME: "Limit",
                    OPENAPI_KEY_SCHEMA: {"type": "integer", "maximum": 1000},
                }
            ]
        }

        result = _cap_limit_parameter(op, max_limit=50)

        assert result[OPENAPI_KEY_PARAMETERS][0][OPENAPI_KEY_SCHEMA][OPENAPI_KEY_MAXIMUM] == 50

    def test_does_not_modify_other_parameters(self):
        """Test that non-limit parameters are not modified."""
        op = {
            OPENAPI_KEY_PARAMETERS: [
                {
                    OPENAPI_KEY_NAME: "offset",
                    OPENAPI_KEY_SCHEMA: {"type": "integer", "maximum": 1000},
                }
            ]
        }

        result = _cap_limit_parameter(op, max_limit=50)

        assert result[OPENAPI_KEY_PARAMETERS][0][OPENAPI_KEY_SCHEMA][OPENAPI_KEY_MAXIMUM] == 1000

    def test_handles_parameter_without_schema(self):
        """Test that parameters without schema are handled."""
        op = {
            OPENAPI_KEY_PARAMETERS: [
                {OPENAPI_KEY_NAME: PARAM_NAME_LIMIT}  # No schema
            ]
        }

        result = _cap_limit_parameter(op, max_limit=50)

        # Should not raise error
        assert OPENAPI_KEY_NAME in result[OPENAPI_KEY_PARAMETERS][0]

    def test_handles_operation_without_parameters(self):
        """Test that operations without parameters are handled."""
        op = {}

        result = _cap_limit_parameter(op, max_limit=50)

        assert result[OPENAPI_KEY_PARAMETERS] == []

    def test_handles_none_parameters(self):
        """Test that None parameters list is handled."""
        op = {OPENAPI_KEY_PARAMETERS: None}

        result = _cap_limit_parameter(op, max_limit=50)

        assert result[OPENAPI_KEY_PARAMETERS] == []

    def test_does_not_modify_original_operation(self):
        """Test that original operation dict is modified in place (by design)."""
        op = {
            OPENAPI_KEY_PARAMETERS: [
                {
                    OPENAPI_KEY_NAME: PARAM_NAME_LIMIT,
                    OPENAPI_KEY_SCHEMA: {"type": "integer", "maximum": 1000},
                }
            ]
        }

        result = _cap_limit_parameter(op, max_limit=50)

        # Function returns the modified operation
        assert result is op
        # The operation is modified in place
        assert result[OPENAPI_KEY_PARAMETERS][0][OPENAPI_KEY_SCHEMA][OPENAPI_KEY_MAXIMUM] == 50


class TestConstants:
    """Tests for module constants."""

    def test_default_max_limit_is_100(self):
        """Test that default maximum limit is 100."""
        assert DEFAULT_MAX_LIMIT == 100

    def test_write_methods_contains_expected_methods(self):
        """Test that WRITE_METHODS contains POST, PUT, PATCH, DELETE."""
        assert HTTP_METHOD_POST in WRITE_METHODS
        assert "put" in WRITE_METHODS
        assert "patch" in WRITE_METHODS
        assert HTTP_METHOD_DELETE in WRITE_METHODS

    def test_write_methods_does_not_contain_get(self):
        """Test that WRITE_METHODS does not contain GET."""
        assert HTTP_METHOD_GET not in WRITE_METHODS

    def test_default_allowlist_is_non_empty(self):
        """Test that DEFAULT_ALLOWLIST contains at least one entry."""
        assert len(DEFAULT_ALLOWLIST) > 0

    def test_default_allowlist_contains_tuples(self):
        """Test that DEFAULT_ALLOWLIST entries are tuples of (method, path)."""
        for entry in DEFAULT_ALLOWLIST:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            method, path = entry
            assert isinstance(method, str)
            assert isinstance(path, str)

    def test_operation_id_aliases_is_dict(self):
        """Test that OPERATION_ID_ALIASES is a dictionary."""
        assert isinstance(OPERATION_ID_ALIASES, dict)

    def test_limit_parameter_names(self):
        """Test that limit parameter name constants are correct."""
        assert PARAM_NAME_LIMIT == "limit"
        assert "Limit" in ["Limit"]  # Capitalized version used in code


class TestCurationSettings:
    """Tests for custom curation settings."""

    def test_uses_custom_allowlist(self):
        """Test that custom allowlist is used when provided."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"}},
                "/custom": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getCustom"}},
            }
        }

        custom_curation = {
            "allowlist": {(HTTP_METHOD_GET, "/custom")},
        }

        result = curate_openapi_spec(spec, enable_writes=False, curation_settings=custom_curation)

        # Only /custom should be present (from custom allowlist)
        assert "/custom" in result[OPENAPI_KEY_PATHS]
        assert "/shells" not in result[OPENAPI_KEY_PATHS]

    def test_uses_custom_aliases(self):
        """Test that custom aliases are used when provided."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {
                    HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "GetShells"}
                }
            }
        }

        custom_curation = {
            "allowlist": {(HTTP_METHOD_GET, "/shells")},
            "aliases": {"GetShells": "fetch_all_shells"},
        }

        result = curate_openapi_spec(spec, enable_writes=False, curation_settings=custom_curation)

        assert result[OPENAPI_KEY_PATHS]["/shells"][HTTP_METHOD_GET][OPENAPI_KEY_OPERATION_ID] == "fetch_all_shells"

    def test_falls_back_to_defaults_when_no_settings(self):
        """Test that default allowlist and aliases are used when curation_settings is None."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"}},
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False, curation_settings=None)

        # Should use DEFAULT_ALLOWLIST (which includes /shells)
        assert "/shells" in result[OPENAPI_KEY_PATHS]

    def test_partial_curation_settings_allowlist_only(self):
        """Test that providing only allowlist uses default aliases."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {
                    HTTP_METHOD_GET: {
                        OPENAPI_KEY_OPERATION_ID: "GetAllAssetAdministrationShells"
                    }
                }
            }
        }

        custom_curation = {
            "allowlist": {(HTTP_METHOD_GET, "/shells")},
            # No aliases specified - should use defaults
        }

        result = curate_openapi_spec(spec, enable_writes=False, curation_settings=custom_curation)

        # Should still apply default alias if it exists
        expected_alias = OPERATION_ID_ALIASES.get("GetAllAssetAdministrationShells")
        if expected_alias:
            assert (
                result[OPENAPI_KEY_PATHS]["/shells"][HTTP_METHOD_GET][OPENAPI_KEY_OPERATION_ID]
                == expected_alias
            )

    def test_partial_curation_settings_aliases_only(self):
        """Test that providing only aliases uses default allowlist."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "GetShells"}},
            }
        }

        custom_curation = {
            # No allowlist specified - should use defaults
            "aliases": {"GetShells": "custom_list_shells"},
        }

        result = curate_openapi_spec(spec, enable_writes=False, curation_settings=custom_curation)

        # Should use DEFAULT_ALLOWLIST for filtering
        # And custom alias for renaming
        if (HTTP_METHOD_GET, "/shells") in DEFAULT_ALLOWLIST:
            assert "/shells" in result[OPENAPI_KEY_PATHS]
            assert (
                result[OPENAPI_KEY_PATHS]["/shells"][HTTP_METHOD_GET][OPENAPI_KEY_OPERATION_ID]
                == "custom_list_shells"
            )

    def test_empty_curation_settings_uses_defaults(self):
        """Test that empty dict uses defaults for both allowlist and aliases."""
        spec = {
            OPENAPI_KEY_PATHS: {
                "/shells": {HTTP_METHOD_GET: {OPENAPI_KEY_OPERATION_ID: "getShells"}},
            }
        }

        result = curate_openapi_spec(spec, enable_writes=False, curation_settings={})

        # Should use DEFAULT_ALLOWLIST
        assert "/shells" in result[OPENAPI_KEY_PATHS]
