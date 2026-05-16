# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for prune_unused_schemas: removes components/schemas not reachable
from any path in the spec, preventing FastMCP from choking on circular
schemas in paths that were filtered out by the allowlist.
"""

import pytest
from aas_mcp_server.tool_curation import prune_unused_schemas


def _spec_with(paths: dict, schemas: dict) -> dict:
    return {
        "openapi": "3.0.3",
        "paths": paths,
        "components": {"schemas": schemas},
    }


# ---------------------------------------------------------------------------
# Basic pruning
# ---------------------------------------------------------------------------

def test_removes_schema_not_referenced_by_any_path():
    """Schemas unreachable from paths are removed."""
    spec = _spec_with(
        paths={
            "/shells": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ShellList"}
                                }
                            }
                        }
                    }
                }
            }
        },
        schemas={
            "ShellList": {"type": "array", "items": {"type": "string"}},
            "Submodel": {"type": "object"},        # not referenced anywhere
            "SubmodelElement": {"type": "object"}, # not referenced anywhere
        },
    )
    result = prune_unused_schemas(spec)
    remaining = set(result["components"]["schemas"].keys())
    assert "ShellList" in remaining
    assert "Submodel" not in remaining
    assert "SubmodelElement" not in remaining


def test_keeps_transitively_referenced_schemas():
    """Schemas reachable via $ref chains from paths are kept."""
    spec = _spec_with(
        paths={
            "/shells": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Shell"}
                            }
                        }
                    }
                }
            }
        },
        schemas={
            "Shell": {
                "type": "object",
                "properties": {
                    "assetInfo": {"$ref": "#/components/schemas/AssetInfo"},
                },
            },
            "AssetInfo": {"type": "object", "properties": {"id": {"type": "string"}}},
            "Orphan": {"type": "object"},  # not reachable
        },
    )
    result = prune_unused_schemas(spec)
    remaining = set(result["components"]["schemas"].keys())
    assert "Shell" in remaining
    assert "AssetInfo" in remaining
    assert "Orphan" not in remaining


def test_keeps_all_schemas_when_all_referenced():
    """When every schema is reachable, nothing is removed."""
    spec = _spec_with(
        paths={
            "/shells": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/A"}
                                }
                            }
                        }
                    }
                }
            }
        },
        schemas={
            "A": {"type": "object", "properties": {"b": {"$ref": "#/components/schemas/B"}}},
            "B": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    )
    result = prune_unused_schemas(spec)
    assert set(result["components"]["schemas"].keys()) == {"A", "B"}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_spec_without_components_unchanged():
    """Spec with no components section is returned as-is."""
    spec = {"openapi": "3.0.3", "paths": {"/shells": {"get": {}}}}
    result = prune_unused_schemas(spec)
    assert result == spec


def test_spec_without_schemas_unchanged():
    """Spec with components but no schemas is returned as-is."""
    spec = {
        "openapi": "3.0.3",
        "paths": {},
        "components": {"securitySchemes": {}},
    }
    result = prune_unused_schemas(spec)
    assert "schemas" not in result.get("components", {})


def test_empty_paths_removes_all_schemas():
    """When there are no paths, all schemas are unreachable and removed."""
    spec = _spec_with(
        paths={},
        schemas={"Shell": {"type": "object"}, "Submodel": {"type": "object"}},
    )
    result = prune_unused_schemas(spec)
    assert result["components"]["schemas"] == {}


def test_handles_circular_schema_refs_without_recursion():
    """Circular $ref chains in schemas do not cause infinite recursion."""
    spec = _spec_with(
        paths={
            "/nodes": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Node"}
                                }
                            }
                        }
                    }
                }
            }
        },
        schemas={
            "Node": {
                "type": "object",
                "properties": {
                    "children": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Node"},  # circular
                    }
                },
            }
        },
    )
    # Must not raise RecursionError
    result = prune_unused_schemas(spec)
    assert "Node" in result["components"]["schemas"]


def test_original_spec_not_mutated():
    """prune_unused_schemas must not modify the input spec in place."""
    spec = _spec_with(
        paths={},
        schemas={"Shell": {"type": "object"}},
    )
    import copy
    original = copy.deepcopy(spec)
    prune_unused_schemas(spec)
    assert spec == original


# ---------------------------------------------------------------------------
# P1 fix: schemas reachable via components/* (not just paths) must be kept
# ---------------------------------------------------------------------------

def test_keeps_schema_reachable_via_components_responses():
    """
    A path referencing #/components/responses/MyResponse where MyResponse
    contains a schema $ref must keep that schema — not prune it.
    """
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/shells": {
                "get": {
                    "responses": {
                        "200": {"$ref": "#/components/responses/ShellListResponse"}
                    }
                }
            }
        },
        "components": {
            "responses": {
                "ShellListResponse": {
                    "description": "List of shells",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ShellList"}
                        }
                    },
                }
            },
            "schemas": {
                "ShellList": {"type": "array", "items": {"type": "string"}},
                "Orphan": {"type": "object"},
            },
        },
    }
    result = prune_unused_schemas(spec)
    remaining = set(result["components"]["schemas"].keys())
    assert "ShellList" in remaining, "ShellList is reachable via components/responses"
    assert "Orphan" not in remaining


def test_keeps_schema_reachable_via_components_request_bodies():
    """
    A path referencing #/components/requestBodies/MyBody where MyBody
    contains a schema $ref must keep that schema.
    """
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/shells": {
                "post": {
                    "requestBody": {"$ref": "#/components/requestBodies/ShellBody"}
                }
            }
        },
        "components": {
            "requestBodies": {
                "ShellBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Shell"}
                        }
                    },
                    "required": True,
                }
            },
            "schemas": {
                "Shell": {"type": "object", "properties": {"id": {"type": "string"}}},
                "Orphan": {"type": "object"},
            },
        },
    }
    result = prune_unused_schemas(spec)
    remaining = set(result["components"]["schemas"].keys())
    assert "Shell" in remaining, "Shell is reachable via components/requestBodies"
    assert "Orphan" not in remaining


def test_keeps_schema_reachable_via_components_parameters():
    """
    A path referencing #/components/parameters/MyParam where MyParam
    contains a schema $ref must keep that schema.
    """
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/shells/{aasIdentifier}": {
                "get": {
                    "parameters": [
                        {"$ref": "#/components/parameters/AasIdParam"}
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {
            "parameters": {
                "AasIdParam": {
                    "name": "aasIdentifier",
                    "in": "path",
                    "required": True,
                    "schema": {"$ref": "#/components/schemas/Identifier"},
                }
            },
            "schemas": {
                "Identifier": {"type": "string", "minLength": 1},
                "Orphan": {"type": "object"},
            },
        },
    }
    result = prune_unused_schemas(spec)
    remaining = set(result["components"]["schemas"].keys())
    assert "Identifier" in remaining, "Identifier is reachable via components/parameters"
    assert "Orphan" not in remaining
