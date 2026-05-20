# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Configuration loader for AAS MCP Server.

This module handles loading and validating configuration from YAML files.
The config file is REQUIRED and defines all component specifications and settings.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from .constants import DEFAULT_CONFIG_PATH, ENV_CONFIG_PATH

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""

    pass


def get_helpful_config_error_message(config_path) -> str:
    """
    Get a helpful error message when config file is missing.

    Args:
        config_path: The path that was attempted

    Returns:
        Detailed error message with instructions
    """
    return f"""Configuration file not found: {config_path}

The AAS MCP Server requires a config.yaml file that defines:
  - Which components to serve (aas-repo, submodel-repo, etc.)
  - Paths to OpenAPI specifications
  - Optional: implementation specs, overlays, and curation settings

To get started:

  1. Create a config.yaml file:

     components:
       aas-repo:
         official_spec: /path/to/AAS-Repository-spec.yaml
       submodel-repo:
         official_spec: /path/to/Submodel-Repository-spec.yaml

  2. Download official AAS OpenAPI specs from:
     https://github.com/admin-shell-io/aas-specs

  3. Provide the config file via:
     - Default location: /app/config/config.yaml (Docker)
     - CLI flag: --config /path/to/config.yaml
     - Environment variable: CONFIG_PATH=/path/to/config.yaml

See config.yaml.example in the repository for a complete template.

For Docker users:
  docker run -v $(pwd)/config.yaml:/app/config/config.yaml \\
             -v $(pwd)/specs:/app/specs \\
             -e AAS_COMPONENT=aas-repo \\
             -e AAS_BASE_URL=http://your-backend:8080 \\
             -i aas-mcp-server
"""


class ComponentConfig:
    """Configuration for a single AAS component."""

    def __init__(
        self, component_name: str, config_data: Dict[str, Any], config_dir: Path
    ):
        """
        Initialize component configuration.

        Args:
            component_name: Name of the component (e.g., "aas-repo")
            config_data: Component configuration dict from YAML
            config_dir: Directory containing the config file (for resolving relative paths)
        """
        self.component_name = component_name
        self.config_dir = config_dir

        # Get spec paths (at least one must be provided)
        self.official_spec = config_data.get("official_spec")
        self.implementation_spec = config_data.get("implementation_spec")
        self.overlay = config_data.get("overlay")

        # Validate: at least one spec must be provided
        if not self.official_spec and not self.implementation_spec:
            raise ConfigError(
                f"Component '{component_name}': at least one of 'official_spec' "
                f"or 'implementation_spec' must be provided"
            )

        # Resolve paths relative to config directory
        if self.official_spec:
            self.official_spec = self._resolve_path(self.official_spec)
        if self.implementation_spec:
            self.implementation_spec = self._resolve_path(self.implementation_spec)
        if self.overlay:
            self.overlay = self._resolve_path(self.overlay)

        # Validate that specified files exist
        self._validate_files()

        # Load curation settings (optional)
        self.curation = config_data.get("curation")

    def _resolve_path(self, path: str) -> Path:
        """
        Resolve a path relative to the config directory if it's not absolute.

        Args:
            path: File path (absolute or relative)

        Returns:
            Resolved absolute Path object
        """
        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        return self.config_dir / path_obj

    def _validate_files(self) -> None:
        """Validate that all specified files exist."""
        if self.official_spec and not self.official_spec.exists():
            raise ConfigError(
                f"Component '{self.component_name}': official_spec file not found: {self.official_spec}"
            )

        if self.implementation_spec and not self.implementation_spec.exists():
            raise ConfigError(
                f"Component '{self.component_name}': implementation_spec file not found: {self.implementation_spec}"
            )

        # Overlay is optional - warn but don't error
        if self.overlay and not self.overlay.exists():
            logger.warning(
                f"Component '{self.component_name}': overlay file specified but not found: {self.overlay}"
            )
            self.overlay = None

    def has_both_specs(self) -> bool:
        """Check if both official and implementation specs are provided."""
        return bool(self.official_spec and self.implementation_spec)

    def __repr__(self) -> str:
        return (
            f"ComponentConfig(name={self.component_name}, "
            f"official={bool(self.official_spec)}, "
            f"implementation={bool(self.implementation_spec)}, "
            f"overlay={bool(self.overlay)})"
        )


class Config:
    """Main configuration for AAS MCP Server."""

    def __init__(self, config_path: Path):
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to config.yaml file

        Raises:
            ConfigError: If config file is missing, invalid, or components are misconfigured
        """
        self.config_path = config_path
        self.config_dir = config_path.parent

        if not config_path.exists():
            raise ConfigError(get_helpful_config_error_message(config_path))

        # Load YAML
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in config file: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to read config file: {e}")

        if not isinstance(self.data, dict):
            raise ConfigError("Config file must contain a YAML dictionary")

        # Load components
        components_data = self.data.get("components", {})
        if not components_data:
            raise ConfigError("Config file must contain a 'components' section")

        self.components: Dict[str, ComponentConfig] = {}
        for component_name, component_data in components_data.items():
            self.components[component_name] = ComponentConfig(
                component_name=component_name,
                config_data=component_data,
                config_dir=self.config_dir,
            )

    def get_component(self, component_name: str) -> ComponentConfig:
        """
        Get configuration for a specific component.

        Args:
            component_name: Name of the component (e.g., "aas-repo")

        Returns:
            ComponentConfig for the specified component

        Raises:
            ConfigError: If component is not defined in config
        """
        if component_name not in self.components:
            available = ", ".join(self.components.keys())
            raise ConfigError(
                f"Component '{component_name}' not found in config. "
                f"Available components: {available}"
            )
        return self.components[component_name]

    def __repr__(self) -> str:
        components_list = ", ".join(self.components.keys())
        return f"Config(path={self.config_path}, components=[{components_list}])"


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from file.

    Resolution order:
    1. Provided config_path argument
    2. CONFIG_PATH environment variable
    3. Default path: /app/config/config.yaml

    Args:
        config_path: Optional explicit path to config file

    Returns:
        Loaded Config object

    Raises:
        ConfigError: If no valid config file is found
    """
    # Determine config file path
    if config_path:
        path = Path(config_path)
    elif ENV_CONFIG_PATH in os.environ:
        path = Path(os.environ[ENV_CONFIG_PATH])
    else:
        path = Path(DEFAULT_CONFIG_PATH)

    return Config(path)
