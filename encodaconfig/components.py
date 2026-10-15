"""
Component introspection for the encodaconfig tool.

Reuses the component loader of `encodapy.components` to resolve expected
inputs and outputs of internal and external components. External
components are addressed with a dotted path type
(e.g. ``my_package.my_component``), exactly as supported at service start.
"""

import pkgutil

import encodapy.components
from typing import Any, Dict, List, Optional

from encodapy.components.component_loader import (
    check_component_type,
    get_component_data_model,
)
from encodapy.components.basic_component_config import ConfigData, InputData, OutputData


def get_builtin_component_types() -> List[str]:
    """List the component types shipped with encodapy.

    Returns:
        List[str]: Sorted list of internal component types
        (subpackages of `encodapy.components`).
    """
    return sorted(
        module.name
        for module in pkgutil.iter_modules(encodapy.components.__path__)
        if module.ispkg and not module.name.startswith("__")
    )


def get_component_io(component_type: str) -> Optional[Dict[str, Any]]:
    """Get the expected inputs and outputs of a component type.

    Uses the same loader functions as the component start, so the result
    matches what the running service expects. For unknown types (module
    not importable) None is returned.

    Args:
        component_type (str): Component type, either a plain name for
            internal components or a dotted path for external ones.

    Returns:
        Optional[Dict[str, Any]]: Dict with the keys:

            - ``inputs`` / ``outputs``: mapping of field name to
              ``{"required": bool, "description": Optional[str]}``
            - ``config``: list of config field names (may be empty)
            - ``available`` (bool): whether the component module was found
        or None if the component type is not available.
    """
    inputs_model = _safe_data_model(component_type, "InputData", InputData)
    outputs_model = _safe_data_model(component_type, "OutputData", OutputData)
    config_model = _safe_data_model(component_type, "ConfigData", ConfigData)
    if inputs_model is None and outputs_model is None and config_model is None:
        return None

    def _field_info(model):
        if model is None:
            return {}
        return {
            name: {
                "required": field.is_required(),
                "description": field.description,
            }
            for name, field in model.model_fields.items()
        }

    report: Dict[str, Any] = {
        "available": True,
        "inputs": {},
        "outputs": {},
        "config": [],
    }
    report["inputs"] = _field_info(inputs_model)
    report["outputs"] = _field_info(outputs_model)
    report["config"] = list(config_model.model_fields) if config_model else []
    return report


def _safe_data_model(component_type: str, subname: str, base):
    try:
        return get_component_data_model(
            component_type=component_type,
            model_subname=subname,
            data_model_type=base,
            none_allowed=True,
        )
    except (TypeError, KeyError):
        return None


__all__ = ["get_builtin_component_types", "get_component_io", "check_component_type"]
