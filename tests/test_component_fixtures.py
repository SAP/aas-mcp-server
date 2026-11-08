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

# Read-only tools each fixture (official SSP-001 specs, aas-specs-api v3.1.3)
# should expose with the integration curation (`[get, "*"]`).
CD_READ_TOOLS = {
    "GenerateSerializationByIds",
    "GetAllConceptDescriptions",
    "GetConceptDescriptionById",
    "GetSelfDescription",
}
EXPECTED_READ_TOOLS = {
    "aas-registry": {
        "GetAllAssetAdministrationShellDescriptors",
        "GetAllSubmodelDescriptorsThroughSuperpath",
        "GetAssetAdministrationShellDescriptorById",
        "GetSelfDescription",
        "GetSubmodelDescriptorByIdThroughSuperpath",
    },
    "submodel-registry": {
        "GetAllSubmodelDescriptors",
        "GetSelfDescription",
        "GetSubmodelDescriptorById",
    },
    "concept-description-repo": CD_READ_TOOLS,
}
# The repository specs have 26-28 read operations; check the core ones only.
EXPECTED_READ_TOOLS_INCLUDE = {
    "aas-repo": {
        "list_shells",  # GetAllAssetAdministrationShells, renamed by the default aliases
        "GetAssetAdministrationShellById",
        "GetAssetInformation_AasRepository",
    },
    "submodel-repo": {
        "GetAllSubmodels",
        "GetSubmodelById",
        "GetSubmodelElementByPath_SubmodelRepo",
    },
}
WRITE_PREFIXES = ("Post", "Put", "Patch", "Delete")


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
@pytest.mark.parametrize("name", sorted(COMPONENT_FILTER_ENV_VARS))
async def test_fixture_generates_read_only_tools(name):
    tools = await _tool_names(_integration_component(name), enable_writes=False)

    assert tools, f"{name}: no tools generated"
    assert not [t for t in tools if t.startswith(WRITE_PREFIXES)]
    if name in EXPECTED_READ_TOOLS:
        assert tools == EXPECTED_READ_TOOLS[name]
    else:
        assert EXPECTED_READ_TOOLS_INCLUDE[name] <= tools


@pytest.mark.asyncio
async def test_concept_description_repo_writes_stay_behind_allowlist():
    """Write operations need both enable_writes and an allowlist entry."""
    component = _integration_component("concept-description-repo")

    # The integration curation only allows GET, so enabling writes adds nothing.
    assert await _tool_names(component, enable_writes=True) == CD_READ_TOOLS

    component.curation = {"allowlist": [["*", "*"]]}
    assert await _tool_names(component, enable_writes=True) == CD_READ_TOOLS | {
        "PostConceptDescription",
        "PutConceptDescriptionById",
        "DeleteConceptDescriptionById",
    }
    assert await _tool_names(component, enable_writes=False) == CD_READ_TOOLS
