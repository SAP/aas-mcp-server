# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
End-to-end tool generation for every supported component.

Builds a real MCP server (no mocks) from each integration fixture spec,
using the same curation as tests/fixtures/integration/config.yaml.template,
and checks which tools an MCP client sees.
"""

from pathlib import Path

import pytest
import yaml
from fastmcp import Client

from aas_mcp_server.config import ComponentConfig
from aas_mcp_server.constants import COMPONENT_FILTER_ENV_VARS
from aas_mcp_server.server import build_mcp_server

INTEGRATION_DIR = Path(__file__).parent / "fixtures" / "integration"

# Read-only tools each fixture should expose with the integration curation
# (`[get, "*"]`).
EXPECTED_READ_TOOLS = {
    "aas-repo": None,  # hand-authored fixture, only checked for "non-empty"
    "submodel-repo": None,
    "aas-registry": None,
    "submodel-registry": {"GetAllSubmodelDescriptors", "GetSubmodelDescriptorById"},
    "concept-description-repo": {
        "GetAllConceptDescriptions",
        "GetConceptDescriptionById",
    },
}


def _integration_component(name: str) -> ComponentConfig:
    template = yaml.safe_load((INTEGRATION_DIR / "config.yaml.template").read_text())
    data = dict(template["components"][name])
    data["official_spec"] = str(INTEGRATION_DIR / f"{name}-official-spec.yaml")
    return ComponentConfig(name, data, INTEGRATION_DIR)


async def _tool_names(component: ComponentConfig, enable_writes: bool) -> set[str]:
    mcp = build_mcp_server(component, "http://127.0.0.1:9", enable_writes)
    async with Client(mcp) as client:
        return {tool.name for tool in await client.list_tools()}


def test_every_component_has_an_integration_fixture():
    """Each supported component is covered by the CI docker startup matrix."""
    template = yaml.safe_load((INTEGRATION_DIR / "config.yaml.template").read_text())
    assert set(template["components"]) == set(COMPONENT_FILTER_ENV_VARS)
    for name in COMPONENT_FILTER_ENV_VARS:
        assert (INTEGRATION_DIR / f"{name}-official-spec.yaml").is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(EXPECTED_READ_TOOLS))
async def test_fixture_generates_read_only_tools(name):
    tools = await _tool_names(_integration_component(name), enable_writes=False)

    assert tools, f"{name}: no tools generated"
    expected = EXPECTED_READ_TOOLS[name]
    if expected is not None:
        assert tools == expected


@pytest.mark.asyncio
async def test_concept_description_repo_writes_stay_behind_allowlist():
    """Write operations need both enable_writes and an allowlist entry."""
    component = _integration_component("concept-description-repo")

    # The integration curation only allows GET, so enabling writes adds nothing.
    assert await _tool_names(component, enable_writes=True) == {
        "GetAllConceptDescriptions",
        "GetConceptDescriptionById",
    }

    component.curation = {"allowlist": [["*", "*"]]}
    assert await _tool_names(component, enable_writes=True) == {
        "GetAllConceptDescriptions",
        "PostConceptDescription",
        "GetConceptDescriptionById",
        "DeleteConceptDescriptionById",
    }
    assert await _tool_names(component, enable_writes=False) == {
        "GetAllConceptDescriptions",
        "GetConceptDescriptionById",
    }
