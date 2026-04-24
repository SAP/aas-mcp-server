# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for wildcard support in allowlist filtering.
"""

import pytest
from aas_mcp_server.tool_curation import _matches_allowlist_pattern


def test_exact_match():
    """Test exact method/path matching."""
    allowlist = {('get', '/shells'), ('post', '/shells')}

    assert _matches_allowlist_pattern('get', '/shells', allowlist)
    assert _matches_allowlist_pattern('post', '/shells', allowlist)
    assert not _matches_allowlist_pattern('delete', '/shells', allowlist)
    assert not _matches_allowlist_pattern('get', '/submodels', allowlist)


def test_wildcard_all_methods_for_path():
    """Test wildcard: all methods for a specific path."""
    allowlist = {('*', '/shells')}

    assert _matches_allowlist_pattern('get', '/shells', allowlist)
    assert _matches_allowlist_pattern('post', '/shells', allowlist)
    assert _matches_allowlist_pattern('put', '/shells', allowlist)
    assert _matches_allowlist_pattern('delete', '/shells', allowlist)
    # Different path should not match
    assert not _matches_allowlist_pattern('get', '/submodels', allowlist)


def test_wildcard_method_for_all_paths():
    """Test wildcard: specific method for all paths."""
    allowlist = {('get', '*')}

    assert _matches_allowlist_pattern('get', '/shells', allowlist)
    assert _matches_allowlist_pattern('get', '/submodels', allowlist)
    assert _matches_allowlist_pattern('get', '/shells/{aasIdentifier}', allowlist)
    # Different method should not match
    assert not _matches_allowlist_pattern('post', '/shells', allowlist)
    assert not _matches_allowlist_pattern('delete', '/submodels', allowlist)


def test_wildcard_all_methods_all_paths():
    """Test wildcard: all methods for all paths."""
    allowlist = {('*', '*')}

    assert _matches_allowlist_pattern('get', '/shells', allowlist)
    assert _matches_allowlist_pattern('post', '/shells', allowlist)
    assert _matches_allowlist_pattern('delete', '/submodels', allowlist)
    assert _matches_allowlist_pattern('put', '/shells/{aasIdentifier}', allowlist)


def test_mixed_wildcards_and_exact():
    """Test combination of wildcards and exact matches."""
    allowlist = {
        ('get', '*'),              # All GET operations
        ('*', '/shells'),          # All methods on /shells
        ('post', '/submodels'),    # Exact: POST /submodels
    }

    # GET wildcard matches
    assert _matches_allowlist_pattern('get', '/shells', allowlist)
    assert _matches_allowlist_pattern('get', '/submodels', allowlist)
    assert _matches_allowlist_pattern('get', '/anything', allowlist)

    # /shells wildcard matches
    assert _matches_allowlist_pattern('post', '/shells', allowlist)
    assert _matches_allowlist_pattern('delete', '/shells', allowlist)

    # Exact POST /submodels matches
    assert _matches_allowlist_pattern('post', '/submodels', allowlist)

    # These should not match
    assert not _matches_allowlist_pattern('delete', '/submodels', allowlist)
    assert not _matches_allowlist_pattern('put', '/other', allowlist)


def test_wildcard_priority():
    """Test that exact matches work alongside wildcards."""
    allowlist = {
        ('get', '*'),              # All GET operations
        ('post', '/shells'),       # Exact POST /shells
    }

    # Both should match via different rules
    assert _matches_allowlist_pattern('get', '/shells', allowlist)  # via wildcard
    assert _matches_allowlist_pattern('post', '/shells', allowlist)  # via exact

    # Only wildcard matches
    assert _matches_allowlist_pattern('get', '/submodels', allowlist)

    # No match
    assert not _matches_allowlist_pattern('post', '/submodels', allowlist)
