"""
Full configuration check for encodaconfig: model validation plus the
component wiring check (are inputs and outputs of the components
available and consistent with the other configuration parts), similar to
the checks performed when the components are started.
"""

from typing import Any, Dict, List


from encodaconfig.components import get_component_io
from encodaconfig.validation import validate_config


def _index_datapoints(config: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    """Index the entity/attribute pairs defined in the configuration.

    Args:
        config (Dict[str, Any]): Raw configuration dict.

    Returns:
        Dict[str, Dict[str, List[str]]]: Mapping
        entity_id -> attribute_id -> list of section names
        ("input", "staticdata", "output").
    """
    index: Dict[str, Dict[str, List[str]]] = {}
    for section, label in [
        ("inputs", "input"),
        ("staticdata", "staticdata"),
        ("outputs", "output"),
    ]:
        for entity in config.get(section, []) or []:
            entity_id = entity.get("id")
            for attribute in entity.get("attributes", []) or []:
                attribute_id = attribute.get("id")
                index.setdefault(entity_id, {}).setdefault(attribute_id, []).append(
                    label
                )
    return index


def check_component_wiring(config_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Check that the component IO allocations match the configuration.

    For every controller component the expected inputs and outputs are
    resolved via the component loader (same functions as at component
    start). Missing entity/attribute references, unexpected allocations
    and required-but-unallocated fields are reported.

    Args:
        config_data (Dict[str, Any]): Raw configuration dict.

    Returns:
        List[Dict[str, str]]: List of issues, each with ``component``,
        ``field``, ``direction`` and ``msg``.
    """
    issues: List[Dict[str, str]] = []
    index = _index_datapoints(config_data)

    for component in config_data.get("controller_components", []) or []:
        component_id = component.get("id", "<unknown>")
        component_type = component.get("type", "<unknown>")
        io = get_component_io(component_type)
        if io is None:
            issues.append(
                {
                    "component": component_id,
                    "field": "type",
                    "direction": "type",
                    "msg": f"Component type '{component_type}' not found or not importable.",
                }
            )
            continue

        for direction, expected in [
            ("inputs", io["inputs"]),
            ("outputs", io["outputs"]),
        ]:
            allocated = component.get(direction, {}) or {}
            for field_name, field_info in expected.items():
                if field_name not in allocated:
                    if field_info["required"]:
                        issues.append(
                            {
                                "component": component_id,
                                "field": field_name,
                                "direction": direction,
                                "msg": f"Required {direction[:-1]} '{field_name}' "
                                "is not allocated.",
                            }
                        )
                    continue
                allocation = allocated[field_name]
                entity_id = allocation.get("entity")
                attribute_id = allocation.get("attribute")
                sections = index.get(entity_id, {}).get(attribute_id)
                if sections is None:
                    issues.append(
                        {
                            "component": component_id,
                            "field": field_name,
                            "direction": direction,
                            "msg": f"Allocated entity '{entity_id}' with attribute "
                            f"'{attribute_id}' is not defined in "
                            "inputs/staticdata/outputs.",
                        }
                    )
            for field_name in allocated:
                if field_name not in expected:
                    issues.append(
                        {
                            "component": component_id,
                            "field": field_name,
                            "direction": direction,
                            "msg": f"Allocation '{field_name}' is not an expected "
                            f"{direction[:-1]} of component type "
                            f"'{component_type}'.",
                        }
                    )
    return issues


def check_configuration(config_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full check: model validation and component wiring.

    Args:
        config_data (Dict[str, Any]): The configuration as a dictionary.

    Returns:
        Dict[str, Any]: Report with the keys ``valid`` (bool),
        ``errors`` (model errors), ``wiring_issues`` (component IO
        issues) and ``model`` (validated `ConfigModel` or None).
    """
    report = validate_config(config_data)
    wiring_issues = check_component_wiring(config_data)
    report["wiring_issues"] = wiring_issues
    if wiring_issues:
        report["valid"] = False
    return report


__all__ = ["check_configuration", "check_component_wiring", "_index_datapoints"]
