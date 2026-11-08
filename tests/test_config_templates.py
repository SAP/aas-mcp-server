# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
The shipped config templates are meant to be copied to config.yaml, so they
must stay loadable YAML whose curation allowlists have the [method, path]
shape that tool_curation expects.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = [
    ROOT / "config.yaml.template",
    ROOT / "configs" / "config.yaml.template",
    ROOT / "tests" / "fixtures" / "integration" / "config.yaml.template",
]


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: str(p.relative_to(ROOT)))
def test_template_is_valid_yaml_with_well_formed_allowlists(template):
    data = yaml.safe_load(template.read_text())

    components = data["components"]
    assert components
    for name, component in components.items():
        for entry in (component.get("curation") or {}).get("allowlist", []):
            assert isinstance(entry, list) and len(entry) == 2, (name, entry)
            assert all(isinstance(part, str) for part in entry), (name, entry)


def test_root_template_keeps_path_placeholders():
    """Unquoted, `/shells/{aasIdentifier}` used to break YAML parsing."""
    data = yaml.safe_load((ROOT / "config.yaml.template").read_text())

    allowlist = data["components"]["aas-repo"]["curation"]["allowlist"]

    assert ["get", "/shells/{aasIdentifier}"] in allowlist
