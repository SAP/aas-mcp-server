# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
OpenAPI schema flattener.

Resolves $ref chains and flattens allOf compositions in components/schemas so
that FastMCP sees plain object schemas with all inherited properties and required
fields directly present.

Problem this solves:
  FastMCP's allOf merger only processes inline sub-schemas. When allOf elements
  are $refs (the standard IDTA AAS pattern), FastMCP misses all inherited fields.
  This module resolves those $refs first, then merges, producing a flat schema
  FastMCP can work with.

Cycle handling:
  The IDTA spec contains genuinely circular $refs (e.g. Entity → SubmodelElement
  → Entity). When a cycle is detected the $ref is kept as-is to break the loop
  instead of recursing infinitely.
"""

from typing import Any, Dict, FrozenSet
import logging

logger = logging.getLogger(__name__)


def flatten_spec_schemas(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve $refs and flatten allOf in every schema in components/schemas.

    Args:
        spec: OpenAPI specification dictionary

    Returns:
        Spec with all component schemas resolved and flattened. The original
        spec is not mutated; a shallow-copied version is returned.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    if not schemas:
        return spec

    logger.info("Flattening allOf / resolving $refs in %d schemas", len(schemas))

    resolved: Dict[str, Any] = {}
    for name in schemas:
        resolved[name] = _resolve(schemas[name], schemas, visiting=frozenset({name}))
        logger.debug("  ✓ %s", name)

    result = dict(spec)
    result["components"] = dict(spec.get("components", {}))
    result["components"]["schemas"] = resolved
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve(
    schema: Any,
    all_schemas: Dict[str, Any],
    visiting: FrozenSet[str],
) -> Any:
    """
    Recursively resolve $refs and flatten allOf in a schema node.

    Args:
        schema:      The schema node to process (may be dict, list, or scalar).
        all_schemas: The full components/schemas dict for $ref lookup.
        visiting:    Schema names currently on the resolution stack (cycle guard).

    Returns:
        Resolved and flattened copy of the schema node.
    """
    if not isinstance(schema, dict):
        return schema

    # --- Bare $ref: resolve to target, or keep if cycle ---
    if "$ref" in schema and len(schema) == 1:
        ref: str = schema["$ref"]
        if not ref.startswith("#/components/schemas/"):
            return schema  # external ref — leave as-is
        name = ref.rsplit("/", 1)[-1]
        if name in visiting:
            return {"$ref": ref}  # cycle break
        if name not in all_schemas:
            return schema  # dangling ref — leave as-is
        return _resolve(all_schemas[name], all_schemas, visiting | {name})

    # --- Recurse into all values first ---
    result: Dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            result[key] = _resolve(value, all_schemas, visiting)
        elif isinstance(value, list):
            result[key] = [
                _resolve(item, all_schemas, visiting)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            result[key] = value

    # --- Flatten allOf if present ---
    if "allOf" in result:
        result = _merge_allof(result)

    return result


def _merge_allof(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge allOf sub-schemas into a single flat schema.

    Combines properties, required lists, and scalar fields (type, description,
    etc.) from all elements. allOf is removed from the result.

    Args:
        schema: Schema dict that contains an "allOf" key (already $ref-resolved).

    Returns:
        Merged schema dict without "allOf".
    """
    merged: Dict[str, Any] = {}

    for element in schema.get("allOf", []):
        if not isinstance(element, dict):
            continue
        # Merge properties
        if "properties" in element:
            merged.setdefault("properties", {}).update(element["properties"])
        # Merge required (extend, deduplicate later)
        if "required" in element:
            existing = merged.get("required", [])
            merged["required"] = existing + [
                f for f in element["required"] if f not in existing
            ]
        # Copy other scalar fields (type, description, pattern, etc.)
        # but don't overwrite already-merged keys, and skip allOf itself.
        #
        # Known limitation (P2): when two allOf elements define the same
        # non-property key with different values (e.g. conflicting
        # additionalProperties or description), the first value wins and later
        # values are silently dropped. Formally, JSON Schema allOf semantics
        # require intersection (the result must satisfy ALL sub-schemas), which
        # for most keywords means "most restrictive wins". In practice the IDTA
        # AAS spec does not produce conflicting keys at the allOf level, so this
        # first-wins behaviour is safe for the current use case. If you encounter
        # a spec that triggers this, the affected tools will still be generated
        # but their validation constraints may be weaker than the original spec.
        for key, val in element.items():
            if key not in ("properties", "required", "allOf") and key not in merged:
                merged[key] = val

    # Carry over any non-allOf keys from the original schema
    for key, val in schema.items():
        if key != "allOf" and key not in merged:
            merged[key] = val

    return merged
