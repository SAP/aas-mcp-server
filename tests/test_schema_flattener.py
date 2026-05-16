# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for schema_flattener: resolves $refs, flattens allOf, breaks cycles.

These tests mirror real IDTA AAS spec patterns that cause FastMCP to fail
when the spec is used unprocessed.
"""

import pytest
from aas_mcp_server.schema_flattener import flatten_spec_schemas


# ---------------------------------------------------------------------------
# Basic $ref resolution
# ---------------------------------------------------------------------------

def test_resolves_simple_ref():
    """A bare $ref in allOf is resolved to the target schema's properties."""
    spec = {
        "components": {
            "schemas": {
                "Base": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
                "Child": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Base"},
                        {"required": ["name"], "properties": {"name": {"type": "string"}}},
                    ]
                },
            }
        }
    }
    result = flatten_spec_schemas(spec)
    child = result["components"]["schemas"]["Child"]

    assert "allOf" not in child
    assert "id" in child["properties"]
    assert "name" in child["properties"]
    assert "id" in child["required"]
    assert "name" in child["required"]


def test_resolves_nested_ref_chain():
    """A → B → C inheritance chain is fully flattened."""
    spec = {
        "components": {
            "schemas": {
                "A": {
                    "type": "object",
                    "required": ["fieldA"],
                    "properties": {"fieldA": {"type": "string"}},
                },
                "B": {
                    "allOf": [
                        {"$ref": "#/components/schemas/A"},
                        {"required": ["fieldB"], "properties": {"fieldB": {"type": "string"}}},
                    ]
                },
                "C": {
                    "allOf": [
                        {"$ref": "#/components/schemas/B"},
                        {"required": ["fieldC"], "properties": {"fieldC": {"type": "string"}}},
                    ]
                },
            }
        }
    }
    result = flatten_spec_schemas(spec)
    c = result["components"]["schemas"]["C"]

    assert "allOf" not in c
    assert {"fieldA", "fieldB", "fieldC"} == set(c["properties"].keys())
    assert {"fieldA", "fieldB", "fieldC"} == set(c["required"])


# ---------------------------------------------------------------------------
# IDTA AAS pattern: AssetAdministrationShell
# ---------------------------------------------------------------------------

def test_flattens_aas_shell_pattern():
    """
    Mirrors the real AssetAdministrationShell schema:
      allOf: [$ref Identifiable, $ref HasDataSpec, {required:[assetInformation], properties:{...}}]
    where Identifiable itself is allOf: [$ref Referable, {required:[id], properties:{id:...}}]
    """
    spec = {
        "components": {
            "schemas": {
                "Referable": {
                    "type": "object",
                    "required": ["modelType"],
                    "properties": {
                        "modelType": {"type": "string"},
                        "idShort": {"type": "string"},
                    },
                },
                "Identifiable": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Referable"},
                        {
                            "required": ["id"],
                            "properties": {
                                "id": {"type": "string"},
                                "administration": {"type": "object"},
                            },
                        },
                    ]
                },
                "HasDataSpecification": {
                    "type": "object",
                    "properties": {
                        "embeddedDataSpecifications": {"type": "array"},
                    },
                },
                "AssetAdministrationShell": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Identifiable"},
                        {"$ref": "#/components/schemas/HasDataSpecification"},
                        {
                            "required": ["assetInformation"],
                            "properties": {
                                "assetInformation": {"type": "object"},
                                "submodels": {"type": "array"},
                            },
                        },
                    ]
                },
            }
        }
    }
    result = flatten_spec_schemas(spec)
    aas = result["components"]["schemas"]["AssetAdministrationShell"]

    assert "allOf" not in aas
    # All inherited + own properties present
    assert {"modelType", "idShort", "id", "administration",
            "embeddedDataSpecifications", "assetInformation", "submodels"} \
        == set(aas["properties"].keys())
    # All required fields from entire chain
    assert {"modelType", "id", "assetInformation"} == set(aas["required"])


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def test_breaks_direct_cycle():
    """A schema that references itself is broken with a $ref, not infinite recursion."""
    spec = {
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Node"},
                        },
                    },
                }
            }
        }
    }
    # Must not raise RecursionError
    result = flatten_spec_schemas(spec)
    node = result["components"]["schemas"]["Node"]
    assert node["properties"]["value"] == {"type": "string"}


def test_breaks_indirect_cycle():
    """A → B → A cycle is broken without infinite recursion."""
    spec = {
        "components": {
            "schemas": {
                "A": {
                    "type": "object",
                    "properties": {
                        "b": {"$ref": "#/components/schemas/B"},
                    },
                },
                "B": {
                    "type": "object",
                    "properties": {
                        "a": {"$ref": "#/components/schemas/A"},
                    },
                },
            }
        }
    }
    result = flatten_spec_schemas(spec)
    # Neither raises nor loses data
    assert "properties" in result["components"]["schemas"]["A"]
    assert "properties" in result["components"]["schemas"]["B"]


def test_breaks_allof_cycle():
    """
    Mirrors real IDTA pattern: Entity allOf-references SubmodelElement_choice
    which references back to Entity via oneOf. Must not hang.
    """
    spec = {
        "components": {
            "schemas": {
                "SubmodelElement_choice": {
                    "oneOf": [
                        {"$ref": "#/components/schemas/Entity"},
                        {"type": "object", "properties": {"value": {"type": "string"}}},
                    ]
                },
                "Entity": {
                    "allOf": [
                        {
                            "required": ["entityType"],
                            "properties": {
                                "entityType": {"type": "string"},
                                "statements": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/SubmodelElement_choice"},
                                },
                            },
                        }
                    ]
                },
            }
        }
    }
    result = flatten_spec_schemas(spec)
    entity = result["components"]["schemas"]["Entity"]
    assert "entityType" in entity.get("properties", {})


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------

def test_schema_without_allof_is_unchanged():
    """Schemas with no allOf or $ref pass through untouched."""
    spec = {
        "components": {
            "schemas": {
                "Simple": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            }
        }
    }
    result = flatten_spec_schemas(spec)
    assert result["components"]["schemas"]["Simple"] == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }


def test_spec_without_components_returned_unchanged():
    """A spec with no components/schemas is returned as-is."""
    spec = {"openapi": "3.0.3", "paths": {}}
    result = flatten_spec_schemas(spec)
    assert result == spec


def test_required_deduplication():
    """required fields from multiple allOf layers are deduplicated."""
    spec = {
        "components": {
            "schemas": {
                "Base": {
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
                "Child": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Base"},
                        # id appears again in child required — should be deduped
                        {"required": ["id", "name"], "properties": {"name": {"type": "string"}}},
                    ]
                },
            }
        }
    }
    result = flatten_spec_schemas(spec)
    child = result["components"]["schemas"]["Child"]
    assert child["required"].count("id") == 1
