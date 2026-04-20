#!/usr/bin/env python3
"""
Orchestration script to generate all derived specs for an AAS implementation.

This script runs the complete pipeline:
1. Generate filter strings (computes intersection with implementation)
2. Generate derived specs for each component (applies filters + overlays)

This is a convenience wrapper around generate_filters.py and generate_derived_spec.py.

Usage:
    # Generate specs for your implementation
    python3 scripts/generate_implementation.py --config configs/my-implementation-config.yaml

    # Generate for SAP BNAC example
    python3 scripts/generate_implementation.py --config configs/sap-bnac-config.example.yaml

    # Dry-run to see what would be generated without writing files
    python3 scripts/generate_implementation.py --config configs/my-config.yaml --dry-run

    # With verbose output
    python3 scripts/generate_implementation.py --config configs/my-config.yaml --log-level DEBUG
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml

# Import library functions
from generate_derived_spec import generate_derived_spec
from generate_filters import generate_filters

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)

# Constants - Configuration
DEFAULT_CONFIG_PATH = "configs/config.yaml.template"
CONFIG_ENV_VAR = "AAS_IMPLEMENTATION_CONFIG"

# Constants - Config file keys
CONFIG_KEY_NAME = "name"
CONFIG_KEY_VERSION = "version"
CONFIG_KEY_COMPONENTS = "components"

# Constants - Logging messages
LOG_SEPARATOR = "=" * 80
LOG_SUBSEPARATOR = "─" * 80
MSG_LOADING_CONFIG = "Loading configuration from:"
MSG_CONFIG_NOT_FOUND = "Configuration file not found"
MSG_CREATE_CONFIG_PROMPT = "Please create a configuration file or use --list-configs to see available configurations."
MSG_HEADER = "AAS IMPLEMENTATION SPEC GENERATION"
MSG_IMPLEMENTATION = "Implementation:"
MSG_CONFIGURATION = "Configuration:"
MSG_MODE_DRY_RUN = "Mode: DRY-RUN (no files will be written)"
MSG_STEP_1_HEADER = "STEP 1: Generate Filter Strings"
MSG_STEP_2_HEADER = "STEP 2: Generate Derived Specs"
MSG_FILTER_GENERATED = "Generated"
MSG_FILTER_STRINGS = "filter strings"
MSG_ENV_VAR_SET = "Set environment variable:"
MSG_SKIP_FILTERS = "Skipping filter generation (--skip-filters specified)"
MSG_USING_EXISTING_ENV = "Using existing environment variables"
MSG_NO_COMPONENTS = "No components found in configuration"
MSG_GENERATING_SPEC = "Generating derived spec for:"
MSG_DRY_RUN_WOULD_GENERATE = "[DRY-RUN] Would generate derived spec for"
MSG_FAILED_TO_GENERATE = "Failed:"
MSG_SUMMARY = "SUMMARY"
MSG_TOTAL_COMPONENTS = "Total components:"
MSG_SUCCESSFUL = "Successful:"
MSG_FAILED = "Failed:"
MSG_DRY_RUN_NOTICE = "This was a dry-run. Run without --dry-run to generate actual files."
MSG_ALL_GENERATED = "All derived specs generated successfully!"
MSG_OUTPUT_DIR = "Output directory:"

# Constants - Argparse
ARG_NAME_CONFIG = "--config"
ARG_NAME_DRY_RUN = "--dry-run"
ARG_NAME_LOG_LEVEL = "--log-level"
ARG_NAME_SKIP_FILTERS = "--skip-filters"
ARG_HELP_CONFIG = f"Path to implementation configuration file (default: {DEFAULT_CONFIG_PATH})"
ARG_HELP_DRY_RUN = "Show what would be done without actually executing commands"
ARG_HELP_LOG_LEVEL = "Set logging level (default: INFO)"
ARG_HELP_SKIP_FILTERS = "Skip filter generation step (use existing environment variables)"
ARG_DEFAULT_LOG_LEVEL = "INFO"
ARG_LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR"]

# Constants - Defaults
DEFAULT_UNKNOWN = "Unknown"
DEFAULT_VERSION_EMPTY = ""
OUTPUT_DIR_DERIVED = "openapi/derived/"

def load_config(config_path: str | None) -> dict[str, Any]:
    """
    Load configuration from YAML file.

    Priority:
    1. Command-line argument (--config)
    2. Environment variable (AAS_IMPLEMENTATION_CONFIG)
    3. Default (configs/basyx-config.yaml)
    """
    if config_path is None:
        config_path = os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)

    if not Path(config_path).exists():
        raise FileNotFoundError(
            f"{MSG_CONFIG_NOT_FOUND}: {config_path}\n"
            f"{MSG_CREATE_CONFIG_PROMPT}"
        )

    logging.info(f"{MSG_LOADING_CONFIG} {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def set_filter_environment_variables(filter_strings: dict[str, str]) -> None:
    """Set filter strings as environment variables for derived spec generation."""
    for env_var, value in filter_strings.items():
        os.environ[env_var] = value
        logging.debug(f"  {MSG_ENV_VAR_SET} {env_var}")


def generate_filter_strings_step(config_path: str, dry_run: bool) -> bool:
    """
    Generate filter strings by calling generate_filters() library function.

    Returns:
        True if successful, False otherwise
    """
    logging.info(f"\n{LOG_SEPARATOR}")
    logging.info(MSG_STEP_1_HEADER)
    logging.info(LOG_SEPARATOR)

    if dry_run:
        logging.info("\n[DRY-RUN] Would call generate_filters() to compute intersection")
        return True

    try:
        # Call library function directly
        filter_strings = generate_filters(config_path=config_path, verbose=True)

        logging.info(f"\n✅ {MSG_FILTER_GENERATED} {len(filter_strings)} {MSG_FILTER_STRINGS}")
        for env_var, value in filter_strings.items():
            logging.debug(f"  {env_var}: {value[:80]}...")

        # Set environment variables for next pipeline step
        set_filter_environment_variables(filter_strings)
        return True

    except Exception as e:
        logging.error(f"\n❌ Filter generation failed: {e}")
        return False


def generate_derived_specs_for_components(
    components: dict[str, Any],
    dry_run: bool
) -> tuple[int, int]:
    """
    Generate derived specs for all components.

    Returns:
        Tuple of (success_count, fail_count)
    """
    logging.info(f"\n{LOG_SEPARATOR}")
    logging.info(MSG_STEP_2_HEADER)
    logging.info(LOG_SEPARATOR)

    success_count = 0
    fail_count = 0

    for component_name in components.keys():
        logging.info(f"\n{LOG_SUBSEPARATOR}")
        logging.info(f"{MSG_GENERATING_SPEC} {component_name}")
        logging.info(LOG_SUBSEPARATOR)

        if dry_run:
            logging.info(f"{MSG_DRY_RUN_WOULD_GENERATE} {component_name}")
            success_count += 1
        else:
            try:
                generate_derived_spec(
                    component=component_name,
                    verbose=True
                )
                success_count += 1
            except (FileNotFoundError, ValueError) as e:
                logging.error(f"  ❌ {MSG_FAILED_TO_GENERATE} {e}")
                fail_count += 1

    return success_count, fail_count


def print_summary(
    total_components: int,
    success_count: int,
    fail_count: int,
    dry_run: bool
) -> None:
    """Print final summary of generation results."""
    logging.info(f"\n{LOG_SEPARATOR}")
    logging.info(MSG_SUMMARY)
    logging.info(LOG_SEPARATOR)
    logging.info(f"{MSG_TOTAL_COMPONENTS} {total_components}")
    logging.info(f"  ✅ {MSG_SUCCESSFUL} {success_count}")
    if fail_count > 0:
        logging.error(f"  ❌ {MSG_FAILED} {fail_count}")

    if dry_run:
        logging.info(f"\n💡 {MSG_DRY_RUN_NOTICE}")
    else:
        logging.info(f"\n✅ {MSG_ALL_GENERATED}")
        logging.info(f"   {MSG_OUTPUT_DIR} {OUTPUT_DIR_DERIVED}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate all derived specs for an AAS implementation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        ARG_NAME_CONFIG,
        help=ARG_HELP_CONFIG,
    )
    parser.add_argument(
        ARG_NAME_DRY_RUN,
        action="store_true",
        help=ARG_HELP_DRY_RUN,
    )
    parser.add_argument(
        ARG_NAME_LOG_LEVEL,
        default=ARG_DEFAULT_LOG_LEVEL,
        choices=ARG_LOG_LEVEL_CHOICES,
        help=ARG_HELP_LOG_LEVEL,
    )
    parser.add_argument(
        ARG_NAME_SKIP_FILTERS,
        action="store_true",
        help=ARG_HELP_SKIP_FILTERS,
    )

    args = parser.parse_args()

    # Set logging level
    logging.getLogger().setLevel(args.log_level)

    # Load configuration
    config_path = args.config or os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)
    config = load_config(config_path)
    config_name = config.get(CONFIG_KEY_NAME, DEFAULT_UNKNOWN)
    config_version = config.get(CONFIG_KEY_VERSION, DEFAULT_VERSION_EMPTY)

    # Print header
    logging.info(LOG_SEPARATOR)
    logging.info(MSG_HEADER)
    logging.info(f"{MSG_IMPLEMENTATION} {config_name} {config_version}")
    logging.info(f"{MSG_CONFIGURATION} {config_path}")
    if args.dry_run:
        logging.info(MSG_MODE_DRY_RUN)
    logging.info(LOG_SEPARATOR)

    # Step 1: Generate filter strings (optional)
    if not args.skip_filters:
        if not generate_filter_strings_step(config_path, args.dry_run):
            sys.exit(1)
    else:
        logging.info(f"\n⏭️  {MSG_SKIP_FILTERS}")
        logging.info(MSG_USING_EXISTING_ENV)

    # Step 2: Generate derived specs
    components = config.get(CONFIG_KEY_COMPONENTS, {})
    if not components:
        logging.error(f"❌ {MSG_NO_COMPONENTS}")
        sys.exit(1)

    success_count, fail_count = generate_derived_specs_for_components(
        components,
        args.dry_run
    )

    # Print summary
    print_summary(len(components), success_count, fail_count, args.dry_run)

    # Exit with error code if any component failed
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
