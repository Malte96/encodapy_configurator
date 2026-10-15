"""
Support for external components in the encodaconfig tool.

External components are normal Python packages that are installed in the
environment (referenced via a dotted path as component `type`, e.g.
``bspw_package_components_example.my_component``) - exactly as at
service start. For convenience, this module additionally supports
loading such packages at runtime from an uploaded ZIP archive or wheel
without installing them permanently.
"""

import importlib
import io
import sys
import tempfile
import zipfile
from pathlib import Path

_loaded_paths: list[str] = []


def register_zip(archive_bytes: bytes, name: str) -> list[str]:
    """Register an uploaded ZIP archive (or wheel) as importable package.

    ZIP archives are extracted to a temporary directory which is
    inserted into ``sys.path``. Pure-Python wheels are appended directly
    (zipimport), wheels with compiled extensions must be installed
    properly (pip).

    Args:
        archive_bytes (bytes): Content of the uploaded archive.
        name (str): Original file name (to detect a wheel).

    Returns:
        List[str]: Top-level packages found in the archive (candidates
        for the component type dotted path).
    """
    if name.endswith(".whl"):
        temp_file = Path(tempfile.gettempdir()) / f"encodaconfig_{name}"
        temp_file.write_bytes(archive_bytes)
        path_entry = str(temp_file)
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="encodaconfig_ext_"))
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            archive.extractall(temp_dir)
        path_entry = str(temp_dir)
    if path_entry not in sys.path:
        sys.path.insert(0, path_entry)
        _loaded_paths.append(path_entry)
    return list_packages(path_entry)


def list_packages(path_entry: str) -> list[str]:
    """List top-level importable packages in a directory or wheel.

    Args:
        path_entry (str): Path added to ``sys.path``.

    Returns:
        List[str]: Names of top-level packages and modules.
    """
    root = Path(path_entry)
    if root.is_file():
        with zipfile.ZipFile(root) as archive:
            names = {
                item.split("/")[0] if "/" in item else item.split(".")[0]
                for item in archive.namelist()
            }
            return sorted(name for name in names if not name.startswith(("_", ".")))
    return sorted(
        entry.name
        for entry in root.iterdir()
        if not entry.name.startswith(("_", "."))
        and (
            (entry.is_dir() and (entry / "__init__.py").exists())
            or entry.suffix == ".py"
        )
    )


def loaded_paths() -> list[str]:
    """Paths registered so far via :func:`register_zip`."""
    return list(_loaded_paths)


def find_component_candidates(path_entry: str) -> list[str]:
    """Find candidate component types in a directory (extracted ZIP).

    A component is a package directory that contains a module named
    ``<directory_name>_config.py`` (the schema used by the encodapy
    component loader: type ``a.b.my_component`` resolves to the module
    ``a.b.my_component.my_component_config``). The candidate type is
    the dotted package path of that directory.

    Args:
        path_entry (str): Path added to ``sys.path``.

    Returns:
        list[str]: Dotted component type candidates (unverified).
    """
    root = Path(path_entry)
    candidates = []
    if root.is_file():
        with zipfile.ZipFile(root) as archive:
            directories = {
                item.rsplit("/", 1)[0]
                for item in archive.namelist()
                if "/" in item and item.endswith(".py")
            }
            for directory in sorted(directories):
                dir_name = directory.rsplit("/", 1)[-1]
                if f"{directory}/{dir_name}_config.py" in archive.namelist():
                    candidates.append(directory.replace("/", "."))
            return candidates
    for config_file in sorted(root.rglob("*_config.py")):
        directory = config_file.parent
        if config_file.name == f"{directory.name}_config.py":
            relative = directory.relative_to(root)
            if relative.parts:
                candidates.append(".".join(relative.parts))
    return candidates


def inspect_component_types(path_entries: list[str]) -> dict[str, str | None]:
    """Inspect all component candidates in the registered paths.

    Unlike :func:`find_component_types`, this returns every candidate
    with the reason why it could not be verified (or None if valid), so
    problems like failed imports (missing dependencies) or missing
    model classes become visible to the user.

    Args:
        path_entries (list[str]): Paths registered via
        :func:`register_zip`.

    Returns:
        dict[str, str | None]: Mapping of dotted component type to an
        error message (None = valid and usable).
    """
    from encodaconfig.components import get_component_io  # pylint: disable=import-outside-toplevel

    inspected: dict[str, str | None] = {}
    for path_entry in path_entries:
        for candidate in find_component_candidates(path_entry):
            if not candidate:
                continue
            name = candidate.rsplit(".", 1)[-1]
            config_module = f"{candidate}.{name}_config"
            try:
                importlib.import_module(config_module)
            except ModuleNotFoundError as error:
                inspected[candidate] = (
                    f"import of `{config_module}` failed: {error} – if the "
                    "missing module is a separate utility package, upload "
                    "its ZIP first and retry"
                )
                continue
            except ImportError as error:
                inspected[candidate] = f"import of `{config_module}` failed: {error}"
                continue
            except (RuntimeError, ValueError, SyntaxError) as error:
                inspected[candidate] = (
                    f"error while importing `{config_module}`: {error}"
                )
                continue
            try:
                io = get_component_io(candidate)
            except (AttributeError, KeyError, TypeError) as error:
                inspected[candidate] = f"could not be resolved: {error}"
                continue
            if io is None:
                inspected[candidate] = (
                    "the component loader could not resolve any "
                    "InputData/OutputData classes – check the classes in "
                    f"`{config_module}` (naming scheme: "
                    "`<Component>InputData`/`<Component>OutputData`)"
                )
            else:
                inspected[candidate] = None
    return dict(sorted(inspected.items()))


def find_component_types(path_entries: list[str]) -> list[str]:
    """Find and verify component types in the registered paths.

    Args:
        path_entries (list[str]): Paths registered via
        :func:`register_zip`.

    Returns:
        list[str]: Dotted component types that could be imported and
        resolved (via the encodapy component loader).
    """
    inspected = inspect_component_types(path_entries)
    return sorted(candidate for candidate, error in inspected.items() if error is None)


__all__ = [
    "find_component_candidates",
    "find_component_types",
    "inspect_component_types",
    "list_packages",
    "loaded_paths",
    "register_zip",
]
