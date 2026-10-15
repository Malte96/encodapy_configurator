"""
encodaconfig - Visual configuration creation and validation for EnCoDaPy.

This subpackage provides a lightweight, model-driven toolkit to create,
edit and validate EnCoDaPy system controller configurations (JSON) in a
web browser. It reuses the Pydantic models and the component loader of
the main `encodapy` package, so new components are supported
automatically without further adaptations.

Main entry points:

- :func:`encodaconfig.validation.validate_config` -
    validate a configuration dict against `ConfigModel`
- :func:`encodaconfig.components.get_component_io` -
    get expected inputs/outputs for a component type (internal or external)
- :func:`encodaconfig.check.check_configuration` -
    full check (models + component IO wiring)
- ``streamlit run encodaconfig/app.py`` - the web UI
"""

from encodaconfig.validation import validate_config
from encodaconfig.components import (
    get_builtin_component_types,
    get_component_io,
)
from encodaconfig.check import check_configuration

__all__ = [
    "validate_config",
    "get_builtin_component_types",
    "get_component_io",
    "check_configuration",
]
