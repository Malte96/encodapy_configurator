"""
Validation of EnCoDaPy configurations against the existing Pydantic models.

No additional validation logic is implemented here: the models in
`encodapy.config.models` and their validators are reused, so validation
behavior is identical to the service start.
"""

from typing import Any

from pydantic import ValidationError

from encodapy.config.models import ConfigModel
from encodapy.utils.error_handling import ConfigError, InterfaceNotActive


def validate_config(config_data: dict[str, Any]) -> dict[str, Any]:
    """Validate a configuration dictionary against `ConfigModel`.

    Args:
        config_data (Dict[str, Any]): The configuration as a dictionary,
            as loaded from JSON or built in the UI.

    Returns:
        Dict[str, Any]: A report dict with the keys:

            - ``valid`` (bool): True if the configuration is valid.
            - ``errors`` (list[dict]): List of errors, each with ``loc``
              (dotted path), ``msg`` and ``type``.
            - ``model`` (Optional[ConfigModel]): The validated model
              instance or None.
    """
    try:
        model = ConfigModel(**config_data)
    except ValidationError as error:
        errors = [
            {
                "loc": ".".join(str(part) for part in err["loc"]) or "<root>",
                "msg": err["msg"],
                "type": err["type"],
            }
            for err in error.errors()
        ]
        return {"valid": False, "errors": errors, "model": None}
    except InterfaceNotActive as error:
        return {
            "valid": False,
            "errors": [{"loc": "interfaces", "msg": str(error), "type": "interface"}],
            "model": None,
        }
    return {"valid": True, "errors": [], "model": model}


def validate_config_file(file_path: str) -> dict[str, Any]:
    """Load and validate a configuration JSON file.

    Args:
        file_path (str): Path to the JSON file.

    Returns:
        Dict[str, Any]: Report as returned by :func:`validate_config`,
        with an additional ``error`` key if the file could not be loaded.
    """
    import json  # pylint: disable=import-outside-toplevel

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            config_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as error:
        return {
            "valid": False,
            "errors": [{"loc": "<file>", "msg": str(error), "type": "file_error"}],
            "model": None,
        }
    report = validate_config(config_data)
    report["model"] = None
    return report


def format_errors(errors: list[dict[str, str]]) -> str:
    """Format a list of errors (as produced by :func:`validate_config`)
    into a human readable multi-line string.

    Args:
        errors (List[Dict[str, str]]): List of error dicts.

    Returns:
        str: Formatted error message, one error per line.
    """
    return "\n".join(f"[{err['loc']}] {err['msg']}" for err in errors)


__all__ = ["ConfigError", "format_errors", "validate_config", "validate_config_file"]
