# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for MCP stdio communication protocol.

Verifies that the MCP server outputs clean JSON-RPC messages on stdout
without banner interference, which is required for MCP protocol compliance.
"""

import subprocess
import json
import pytest
import shutil
from pathlib import Path


def find_aas_mcp_server():
    """Find the aas-mcp-server executable."""
    # Try to find in PATH
    which_result = shutil.which("aas-mcp-server")
    if which_result:
        return which_result

    # Try development .venv
    venv_path = Path(__file__).parent.parent / ".venv" / "bin" / "aas-mcp-server"
    if venv_path.exists():
        return str(venv_path)

    pytest.skip("aas-mcp-server executable not found")


@pytest.fixture
def server_command(tmp_path):
    """Get the server command for testing."""
    executable = find_aas_mcp_server()

    # Create minimal test config with docs specs
    config_path = tmp_path / "config.yaml"
    docs_dir = Path(__file__).parent.parent / "docs"
    official_spec = (
        docs_dir
        / "openapi"
        / "AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml"
    )

    if official_spec.exists():
        config_content = f"""
components:
  aas-repo:
    official_spec: {official_spec}
    curation:
      allowlist:
        - [get, "*"]
      aliases: {{}}
"""
    else:
        # Fallback: create empty spec
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text("""
openapi: 3.0.3
info:
  title: Test
  version: 1.0.0
paths: {}
""")
        config_content = f"""
components:
  aas-repo:
    official_spec: {spec_path}
    curation:
      allowlist:
        - [get, "*"]
      aliases: {{}}
"""

    config_path.write_text(config_content)

    return [
        executable,
        "--component",
        "aas-repo",
        "--base-url",
        "http://localhost:8080",
        "--config",
        str(config_path),
        "--log-level",
        "WARNING",
    ]


def test_mcp_initialize_clean_json(server_command):
    """Test that MCP initialize returns clean JSON without banner."""
    # MCP initialize request
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }

    # Run server and send request
    proc = subprocess.Popen(
        server_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = proc.communicate(input=json.dumps(request) + "\n", timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("Server did not respond within timeout")

    # Parse response - should be clean JSON on stdout
    try:
        response = json.loads(stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(f"Server output is not valid JSON. stdout: {stdout[:500]}")

    # Verify MCP response structure
    assert response.get("jsonrpc") == "2.0", "Missing or invalid jsonrpc field"
    assert response.get("id") == 1, "Response ID does not match request ID"
    assert "result" in response, "Missing result field"

    # Verify server info
    server_info = response["result"].get("serverInfo", {})
    assert server_info.get("name") == "AAS MCP Server (aas-repo)", (
        "Incorrect server name"
    )
    assert "version" in server_info, "Missing version in serverInfo"


def test_mcp_no_banner_interference(server_command):
    """Test that FastMCP banner does not interfere with JSON output."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }

    proc = subprocess.Popen(
        server_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, _ = proc.communicate(input=json.dumps(request) + "\n", timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("Server did not respond within timeout")

    # Verify no banner text in stdout
    banner_indicators = ["FastMCP", "gofastmcp.com", "╭", "╰", "▄▀"]
    for indicator in banner_indicators:
        assert indicator not in stdout, (
            f"Banner interference detected: '{indicator}' found in stdout"
        )

    # Verify output starts with valid JSON
    assert stdout.strip().startswith("{"), "Output does not start with JSON object"
    assert stdout.strip().endswith("}"), "Output does not end with JSON object"


def test_mcp_capabilities_response(server_command):
    """Test that server returns expected MCP capabilities."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }

    proc = subprocess.Popen(
        server_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, _ = proc.communicate(input=json.dumps(request) + "\n", timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("Server did not respond within timeout")

    response = json.loads(stdout.strip())

    # Verify capabilities
    capabilities = response["result"].get("capabilities", {})
    assert "tools" in capabilities, "Missing tools capability"
    assert "prompts" in capabilities, "Missing prompts capability"
    assert "resources" in capabilities, "Missing resources capability"

    # Verify protocol version
    protocol_version = response["result"].get("protocolVersion")
    assert protocol_version == "2024-11-05", (
        f"Unexpected protocol version: {protocol_version}"
    )
