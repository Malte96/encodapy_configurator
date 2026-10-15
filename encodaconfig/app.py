"""
Streamlit web UI for creating and validating EnCoDaPy configurations.

Run with:

    streamlit run encodaconfig/app.py

The app is a thin layer over the core modules (validation, components,
check, env requirements): the configuration is held in the Streamlit
session state, can be exported as JSON (download or optional file path)
and is not connected to a running EnCoDaPy service.
"""

import json
import re
import zipfile
from typing import Any

import streamlit as st

from encodaconfig.check import check_configuration
from encodaconfig.components import get_builtin_component_types, get_component_io
from encodaconfig.env_requirements import generate_env_template, get_env_requirements
from encodaconfig.external import (
    inspect_component_types,
    loaded_paths,
    register_zip,
)
from encodapy.config.types import Interfaces
from encodapy.utils.units import TimeUnits

st.set_page_config(page_title="EnCoDaPy Configurator", page_icon="⚙️", layout="wide")

_DANGER_BUTTON_CSS = """
<style>
/* Delete/danger buttons use type="primary" and are colored red. */
.stButton > button[kind="primary"] {
    background-color: #dc3545;
    color: #ffffff;
    border: 1px solid #b02a37;
    font-family: "Source Sans Pro", "Segoe UI Emoji", "Noto Color Emoji",
        "Apple Color Emoji", sans-serif;
}
.stButton > button[kind="primary"]:hover {
    background-color: #c82333;
    color: #ffffff;
}
.stButton > button[kind="primary"]:focus {
    background-color: #b02a37;
    color: #ffffff;
}
</style>
"""
st.markdown(_DANGER_BUTTON_CSS, unsafe_allow_html=True)

GITHUB_REPO_URL = "https://github.com/gewv-tu-dresden/encodapy"
DOCS_URL = "https://gewv-tu-dresden.github.io/encodapy/"
DOCS_MODEL_URL = f"{DOCS_URL}basic_service/config_models.html"
DOCS_ENV_URL = f"{DOCS_URL}basic_service/env_values.html"
DOCS_CONFIG_URL = f"{DOCS_URL}basic_service.html"
DOCS_COMPONENTS_URL = f"{DOCS_URL}components.html"
DOCS_MODEL_SECTIONS = {
    "ConfigModel": f"{DOCS_MODEL_URL}#encodapy.config.models.ConfigModel",
    "interfaces": f"{DOCS_MODEL_URL}#encodapy.config.models.InterfaceModel",
    "inputs": f"{DOCS_MODEL_URL}#encodapy.config.models.InputModel",
    "staticdata": f"{DOCS_MODEL_URL}#encodapy.config.models.StaticDataModel",
    "outputs": f"{DOCS_MODEL_URL}#encodapy.config.models.OutputModel",
    "attributes": f"{DOCS_MODEL_URL}#encodapy.config.models.AttributeModel",
    "commands": f"{DOCS_MODEL_URL}#encodapy.config.models.CommandModel",
    "components": f"{DOCS_MODEL_URL}#encodapy.components.basic_component_config.ControllerComponentModel",
    "settings": f"{DOCS_MODEL_URL}#encodapy.config.models.ControllerSettingModel",
    "calculation": f"{DOCS_MODEL_URL}#encodapy.config.models.TimeSettingsCalculationModel",
    "env": f"{DOCS_ENV_URL}#encodapy.config.env_values",
}
GEWV_URL = "https://tu-dresden.de/ing/maschinenwesen/iet/gewv"
LOGO_URL = (
    "https://raw.githubusercontent.com/gewv-tu-dresden/encodapy/main/"
    "docs/source/logos/GEWV_Logo.svg"
)

INTERFACES = ["mqtt", "fiware", "file"]
ENTITY_SECTIONS = {
    "inputs": "input",
    "staticdata": "staticdata",
    "outputs": "output",
}
SECTION_DESCRIPTIONS = {
    "inputs": "Input data of the controller (e.g. sensor data).",
    "staticdata": "Static data (e.g. device parameterization).",
    "outputs": "Output data of the controller (e.g. results, commands).",
}


@st.cache_data(show_spinner=False)
def _get_component_io_cached(component_type: str):
    """Cached wrapper: component imports are expensive."""
    if not component_type:
        return None
    try:
        return get_component_io(component_type)
    except (AttributeError, ImportError, KeyError, TypeError):
        return None


@st.cache_data(show_spinner=False)
def _model_field_help(model_path: str, field_name: str) -> str | None:
    """Build the help text for a form field directly from the EnCoDaPy
    model field description, including a link to the model docs.

    Args:
        model_path (str): Import path of the model class
            (e.g. "encodapy.config.models.OutputModel").
        field_name (str): Name of the field.

    Returns:
        Optional[str]: Help text with description + docs link or None.
    """
    try:
        module_name, class_name = model_path.rsplit(".", 1)
        module = __import__(module_name, fromlist=[class_name])
        model_class = getattr(module, class_name)
        field = model_class.model_fields.get(field_name)
    except (ImportError, AttributeError):
        return None
    description = (field.description or "").strip() if field is not None else ""
    docstring_description = _docstring_field_description(model_path, field_name)
    text = description or docstring_description
    return text if text else None


def _field_docs_link(model_path: str) -> str:
    """Clickable markdown docs link for a model class (for captions)."""
    class_name = model_path.rsplit(".", 1)[-1]
    class_anchor = f"encodapy.{model_path.split('encodapy.', 1)[-1]}"
    return f"📖 [Docs: {class_name}]({DOCS_MODEL_URL}#{class_anchor})"


MODEL_LINK_LABELS = {
    "interfaces": "InterfaceModel",
    "inputs": "InputModel",
    "staticdata": "StaticDataModel",
    "outputs": "OutputModel",
    "attributes": "AttributeModel",
    "commands": "CommandModel",
    "components": "ControllerComponentModel",
    "settings": "ControllerSettingModel",
    "calculation": "TimeSettingsCalculationModel",
    "env": "env_values",
}


@st.cache_data(show_spinner=False)
def _model_docs_link(section: str) -> str:
    """Markdown docs link (config_models.html anchor) for a config section."""
    url = DOCS_MODEL_SECTIONS.get(section, DOCS_MODEL_URL)
    label = MODEL_LINK_LABELS.get(section, section)
    return f"📖 [Docs: {label}]({url})"


@st.cache_data(show_spinner=False)
def _docstring_field_description(model_path: str, field_name: str) -> str:
    """Extract the field description from the model class docstring.

    The EnCoDaPy models document their fields in the Google-style
    'Attributes:' section of the class docstring (not via
    Field(description=...)). This parser extracts the description for
    a single field from there.

    Args:
        model_path (str): Import path of the model class.
        field_name (str): Name of the field.

    Returns:
        str: The description or an empty string.
    """
    try:
        module_name, class_name = model_path.rsplit(".", 1)
        module = __import__(module_name, fromlist=[class_name])
        model_class = getattr(module, class_name)
        docstring = model_class.__doc__ or ""
    except (ImportError, AttributeError):
        return ""
    attributes = docstring.split("Attributes:", 1)
    if len(attributes) < 2:
        return ""
    pattern = re.compile(r"^\s+(" + re.escape(field_name) + r")\s*\([^)]*\):\s*(.+)$")
    lines = attributes[1].split("\n")
    for idx, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            description = match.group(2).strip()
            for cont in lines[idx + 1 :]:
                if cont.strip() and not cont.strip().startswith(
                    tuple("abcdefghijklmnopqrstuvwxyz_")
                ):
                    description += " " + cont.strip().rstrip("\\")
                else:
                    break
            return " ".join(description.split())
    return ""


def new_config() -> dict[str, Any]:
    """Return a minimal valid starting configuration."""
    return {
        "name": "new_config",
        "interfaces": {"mqtt": False, "fiware": True, "file": False},
        "inputs": [],
        "outputs": [],
        "staticdata": [],
        "controller_components": [],
        "controller_settings": {
            "time_settings": {
                "calculation": {
                    "timerange": 60,
                    "timerange_unit": "minute",
                    "timestep": 1,
                    "timestep_unit": "second",
                    "sampling_time": 1,
                    "sampling_time_unit": "minute",
                }
            }
        },
    }


def load_config_to_state(config: dict[str, Any]) -> None:
    """Put a configuration dict into the session state (normalized)."""
    base = new_config()
    for key, value in config.items():
        base[key] = value
    st.session_state["config"] = base


def ensure_state() -> None:
    """Initialize the session state if not present."""
    if "config" not in st.session_state:
        load_config_to_state(new_config())


def component_type_options() -> list[str]:
    """Selectable component types: built-in + loaded external components."""
    options = get_builtin_component_types()
    for component_type in st.session_state.get("ext_component_types", []) or []:
        if component_type not in options:
            options.append(component_type)
    return options


ENTITY_MODEL_PATHS = {
    "inputs": "encodapy.config.models.InputModel",
    "staticdata": "encodapy.config.models.StaticDataModel",
    "outputs": "encodapy.config.models.OutputModel",
}


def render_entity(section: str, index: int) -> None:
    """Render form fields for one entity (input/staticdata/output)."""
    config = st.session_state["config"]
    entities = config[section]
    entity = entities[index]
    model_path = ENTITY_MODEL_PATHS[section]
    col_id, col_iface, col_col = st.columns([3, 2, 1])
    entity["id"] = col_id.text_input(
        f"ID {index + 1}",
        value=entity.get("id", ""),
        key=f"{section}_{index}_id",
        help=_model_field_help(model_path, "id"),
    )
    iface_value = entity.get("interface", "fiware")
    iface_options = [e.value for e in Interfaces]
    entity["interface"] = col_iface.selectbox(
        f"Interface {index + 1}",
        options=iface_options,
        index=iface_options.index(iface_value),
        key=f"{section}_{index}_iface",
        help=_model_field_help(model_path, "interface"),
    )
    if col_col.button(
        "🗑 Delete",
        key=f"{section}_{index}_del",
        type="primary",
    ):
        entities.pop(index)
        st.rerun()
    entity["id_interface"] = st.text_input(
        f"ID interface {index + 1} (empty = ID)",
        value=entity.get("id_interface", ""),
        key=f"{section}_{index}_idiface",
        help=_model_field_help(model_path, "id_interface"),
    )
    st.caption(_field_docs_link(model_path))
    attributes = entity.setdefault("attributes", [])
    commands = entity.setdefault("commands", []) if section == "outputs" else []
    if not attributes and not commands:
        st.warning(
            f"This {ENTITY_SECTIONS[section]} has neither attributes nor "
            "commands – add at least one of them, otherwise it cannot be "
            "used by components.",
            icon="⚠️",
        )
    if st.button(
        f"+ Add attribute ({entity['id'] or section})",
        key=f"{section}_{index}_addattr",
    ):
        attributes.append({"id": ""})
        st.rerun()
    for attr_idx, attribute in enumerate(attributes):
        col_a, col_b, col_c = st.columns([3, 3, 1])
        attribute["id"] = col_a.text_input(
            f"Attribute {attr_idx + 1}",
            value=attribute.get("id", ""),
            key=f"{section}_{index}_attr{attr_idx}_id",
            help=_model_field_help("encodapy.config.models.AttributeModel", "id"),
        )
        attribute["id_interface"] = col_b.text_input(
            f"Attribute ID interface {attr_idx + 1} (empty = ID)",
            value=attribute.get("id_interface", ""),
            key=f"{section}_{index}_attr{attr_idx}_idiface",
            help=_model_field_help(
                "encodapy.config.models.AttributeModel", "id_interface"
            ),
        )
        if col_c.button(
            "🗑", key=f"{section}_{index}_attr{attr_idx}_del", type="primary"
        ):
            attributes.pop(attr_idx)
            st.rerun()
    if section == "outputs":
        commands = entity.setdefault("commands", [])
        st.markdown(
            f"**Commands** — commands the controller can send via this "
            "output (e.g. switching commands). "
            f"{_model_docs_link('commands')}"
        )
        if st.button(
            f"+ Add command ({entity['id'] or section})",
            key=f"{section}_{index}_addcmd",
        ):
            commands.append({"id": ""})
            st.rerun()
        for cmd_idx, command in enumerate(commands):
            col_a, col_b, col_c = st.columns([3, 3, 1])
            command["id"] = col_a.text_input(
                f"Command {cmd_idx + 1}",
                value=command.get("id", ""),
                key=f"{section}_{index}_cmd{cmd_idx}_id",
                help=_model_field_help("encodapy.config.models.CommandModel", "id"),
            )
            command["id_interface"] = col_b.text_input(
                f"Command ID interface {cmd_idx + 1} (empty = ID)",
                value=command.get("id_interface", ""),
                key=f"{section}_{index}_cmd{cmd_idx}_idiface",
                help=_model_field_help(
                    "encodapy.config.models.CommandModel", "id_interface"
                ),
            )
            if col_c.button(
                "🗑", key=f"{section}_{index}_cmd{cmd_idx}_del", type="primary"
            ):
                commands.pop(cmd_idx)
                st.rerun()


def render_component(index: int) -> None:
    """Render form fields for one controller component."""
    config = st.session_state["config"]
    components = config["controller_components"]
    component = components[index]
    col_id, col_del = st.columns([6, 1])
    component["id"] = col_id.text_input(
        f"Component ID {index + 1}",
        value=component.get("id", ""),
        key=f"comp_{index}_id",
        help="Unique ID of the component within the controller.",
    )
    if col_del.button("🗑️", key=f"comp_{index}_del", type="primary"):
        components.pop(index)
        st.rerun()
    options = component_type_options()
    current_type = component.get("type", "")
    type_options = [""] + options
    if current_type and current_type not in type_options:
        type_options.append(current_type)
    component["type"] = st.selectbox(
        f"Component type {index + 1} (search, or type a dotted path for "
        "external components)",
        options=type_options,
        index=type_options.index(current_type) if current_type in type_options else 0,
        key=f"comp_{index}_type",
        accept_new_options=True,
        filter_mode="fuzzy",
        help="Built-in component types are listed; start typing to search. "
        "For external components, enter the dotted path (e.g. "
        "'my_package.my_component') of a package installed in the "
        "environment.",
    )
    io = (
        _get_component_io_cached(component.get("type", ""))
        if component.get("type")
        else None
    )
    if io is None:
        if component.get("type"):
            st.warning(
                f"Component type '{component['type']}' not found "
                "(module not importable or wrong name). External "
                "components must be installed as a package or loaded via "
                "ZIP/wheel in the sidebar."
            )
        return
    st.success(
        f"✅ Component recognized – {len(io['inputs'])} inputs, "
        f"{len(io['outputs'])} outputs, {len(io['config'])} config fields."
    )
    st.caption(
        "Map each field to an entity + attribute/command from your inputs/"
        "staticdata/outputs (dropdowns). Output fields can also reference "
        "commands defined on an output. Optional fields may stay empty – "
        "they are then omitted from the configuration."
    )
    for direction in ["inputs", "outputs"]:
        expected = io[direction]
        if not expected:
            continue
        allocated = component.setdefault(direction, {})
        st.markdown(
            f"**{direction.capitalize()}** "
            f"({'all required' if all(f['required'] for f in expected.values()) else '⚠️ = required'})"
        )
        for field_name, field_info in expected.items():
            current = allocated.setdefault(field_name, {"entity": "", "attribute": ""})
            options = datapoint_options(st.session_state["config"])
            col_e, col_a, col_req = st.columns([3, 3, 2])
            entity_options = [""] + list(options)
            entity_value = current.get("entity", "")
            if entity_value and entity_value not in entity_options:
                entity_options.append(entity_value)
            current["entity"] = col_e.selectbox(
                f"{field_name} → Entity",
                options=entity_options,
                index=entity_options.index(entity_value) if entity_value else 0,
                key=f"comp_{index}_{direction}_{field_name}_entity",
                help=field_info.get("description") or None,
            )
            attribute_options = [""] + list(
                options.get(current["entity"], {}).get("attributes", {})
            )
            attribute_value = current.get("attribute", "")
            if attribute_value and attribute_value not in attribute_options:
                attribute_options.append(attribute_value)
            current["attribute"] = col_a.selectbox(
                f"{field_name} → Attribute/Command"
                if direction == "outputs"
                else f"{field_name} → Attribute",
                options=attribute_options,
                index=attribute_options.index(attribute_value)
                if attribute_value in attribute_options
                else 0,
                key=f"comp_{index}_{direction}_{field_name}_attribute",
            )
            col_req.markdown("⚠️ required" if field_info["required"] else "optional")
    if io["config"]:
        config_fields = component.setdefault("config", {})
        st.markdown("**Config (static values or references)**")
        st.caption(
            "Config fields are static component settings: either as a "
            "direct value (JSON) or as a reference to an entity + "
            "attribute of your staticdata. Leave unused fields empty."
        )
        for field_name in io["config"]:
            value = config_fields.get(field_name, "")
            is_reference = isinstance(value, dict) and "entity" in value
            is_direct = isinstance(value, dict) and "value" in value
            mode_index = 1 if is_reference else 2 if is_direct else 0
            mode = st.radio(
                f"{field_name}: mode",
                ["not set", "Reference (entity + attribute)", "Direct value (JSON)"],
                index=mode_index,
                key=f"comp_{index}_config_{field_name}_mode",
                horizontal=True,
            )
            if mode == "not set":
                config_fields.pop(field_name, None)
                continue
            if mode == "Reference (entity + attribute)":
                options = datapoint_options(st.session_state["config"])
                entry = value if is_reference else {}
                entity_options = [""] + list(options)
                entity_value = entry.get("entity", "")
                col_e, col_a = st.columns(2)
                entity = col_e.selectbox(
                    f"{field_name} → Entity",
                    options=entity_options,
                    index=entity_options.index(entity_value) if entity_value else 0,
                    key=f"comp_{index}_config_{field_name}_entity",
                )
                attribute = col_a.selectbox(
                    f"{field_name} → Attribute",
                    options=[""] + list(options.get(entity, {}).get("attributes", {})),
                    key=f"comp_{index}_config_{field_name}_attribute",
                )
                if entity and attribute:
                    config_fields[field_name] = {
                        "entity": entity,
                        "attribute": attribute,
                    }
                else:
                    config_fields.pop(field_name, None)
                continue
            raw = st.text_input(
                f'{field_name} → Value (JSON, e.g. 100, "air" or {{"a": 1}})',
                value=json.dumps(value["value"]) if is_direct else str(value or ""),
                key=f"comp_{index}_config_{field_name}_value",
            )
            if raw:
                try:
                    config_fields[field_name] = {"value": json.loads(raw)}
                except json.JSONDecodeError:
                    config_fields[field_name] = {"value": raw}
            else:
                config_fields.pop(field_name, None)


def datapoint_options(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build the selectable entity/attribute options from the config."""
    options: dict[str, dict[str, Any]] = {}
    for section in ENTITY_SECTIONS:
        for entity in config.get(section, []) or []:
            if not entity.get("id"):
                continue
            entry = options.setdefault(entity["id"], {"attributes": {}, "sections": []})
            entry["sections"].append(section)
            for attribute in entity.get("attributes", []) or []:
                if attribute.get("id"):
                    entry["attributes"].setdefault(attribute["id"], section)
            for command in entity.get("commands", []) or []:
                if command.get("id"):
                    entry["attributes"].setdefault(command["id"], section)
    return options


def render_report(report: dict[str, Any]) -> None:
    """Render the validation report in a readable, grouped way."""
    errors: list[dict[str, str]] = report["errors"]
    wiring_issues: list[dict[str, str]] = report["wiring_issues"]
    if not errors and not wiring_issues:
        st.success(
            "✅ **Configuration is valid.** All model checks and the "
            "component wiring passed – the configuration can be exported "
            "and used."
        )
        return
    st.subheader("Model validation (Pydantic)")
    st.caption(
        "These errors come directly from the EnCoDaPy models "
        "(`ConfigModel`) – the same checks as at service start."
    )
    if errors:
        for err in errors:
            st.error(f"**{err['loc']}** – {err['msg']}")
    else:
        st.markdown("✅ No model errors.")
    st.subheader("Component wiring")
    st.caption(
        "Checks whether the mapped entities/attributes exist, all "
        "required inputs/outputs are allocated and no unknown mappings "
        "are present."
    )
    if wiring_issues:
        by_component: dict[str, list[dict[str, str]]] = {}
        for issue in wiring_issues:
            by_component.setdefault(issue["component"], []).append(issue)
        for component_id, issues in by_component.items():
            with st.expander(
                f"🔧 {component_id} ({len(issues)} issues)", expanded=True
            ):
                for issue in issues:
                    st.warning(f"{issue['direction']}/{issue['field']}: {issue['msg']}")
    else:
        st.markdown("✅ No wiring issues.")


def main() -> None:
    """Main entry point of the Streamlit app."""
    ensure_state()
    config = st.session_state["config"]

    with st.sidebar:
        st.markdown(
            f'<a href="{GEWV_URL}" target="_blank">'
            f'<img src="{LOGO_URL}" width="180"></a>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"**EnCoDaPy Configurator** — visual creation and validation "
            f"of EnCoDaPy configurations.\n\n"
            f"📄 Docs: [Configuration]({DOCS_CONFIG_URL}) · "
            f"[Components]({DOCS_COMPONENTS_URL})\n\n"
            f"🐙 [GitHub: gewv-tu-dresden/encodapy]({GITHUB_REPO_URL})"
        )
        st.divider()
        st.markdown("#### Validate an existing configuration")
        uploaded = st.file_uploader(
            "Upload a JSON file – it is validated and can then be edited in all tabs",
            type="json",
            key="config_upload",
        )
        if uploaded is not None and uploaded.name != st.session_state.get(
            "uploaded_name"
        ):
            try:
                load_config_to_state(json.load(uploaded))
                st.session_state["uploaded_name"] = uploaded.name
                st.rerun()
            except json.JSONDecodeError as error:
                st.error(f"Invalid JSON: {error}")
        if st.session_state.get("uploaded_name"):
            st.caption(f"Loaded: {st.session_state['uploaded_name']}")
        if st.button("🗑️ Start new (empty) configuration"):
            load_config_to_state(new_config())
            st.session_state.pop("uploaded_name", None)
            st.rerun()
        st.divider()
        st.markdown("#### External components")
        st.caption(
            "**Option 1 (recommended, as at service start):** install the "
            "package in the environment (`pip install "
            "bspw_package_components_example`) and enter the type as "
            "dotted path.\n\n"
            "**Option 2:** upload the ZIP/wheel of the package – it is "
            "made importable for this session (no writes to the "
            "environment)."
        )
        ext_upload = st.file_uploader(
            "ZIP or wheel of a component package",
            type=["zip", "whl"],
            key="ext_upload",
        )
        ext_upload_id = (
            f"{ext_upload.name}:{len(ext_upload.getvalue())}"
            if ext_upload is not None
            else None
        )
        if ext_upload is not None and ext_upload_id != st.session_state.get(
            "ext_loaded_id"
        ):
            try:
                packages = register_zip(ext_upload.getvalue(), ext_upload.name)
                st.session_state["ext_loaded_id"] = ext_upload_id
                st.session_state["ext_packages"] = packages
                _get_component_io_cached.clear()
                inspected = inspect_component_types(loaded_paths())
                component_types = sorted(
                    candidate for candidate, error in inspected.items() if error is None
                )
                failed = {
                    candidate: error
                    for candidate, error in inspected.items()
                    if error is not None
                }
                previous_types = st.session_state.get("ext_component_types", []) or []
                st.session_state["ext_component_types"] = sorted(
                    set(previous_types) | set(component_types)
                )
                st.session_state["ext_failed_types"] = failed
                if component_types:
                    st.success(
                        "Package loaded. Found component types: "
                        + ", ".join(f"`{t}`" for t in component_types)
                        + " – select them in the Components tab."
                    )
                else:
                    if not inspected:
                        st.info(
                            "Package loaded (top-level packages: "
                            + ", ".join(packages)
                            + "). No components found – if this is a "
                            "utility/helper package (no `_config.py` "
                            "component modules), that is fine: its "
                            "modules are now importable for subsequently "
                            "loaded component packages. Load the component "
                            "ZIP afterwards."
                        )
                    else:
                        st.warning(
                            "Package loaded (top-level packages: "
                            + ", ".join(packages)
                            + "), but no usable components found. See the "
                            "error details."
                        )
                if failed:
                    st.error(
                        f"{len(failed)} component candidate(s) could not "
                        "be loaded – see details below.",
                        icon="⚠️",
                    )
                    st.session_state["ext_load_errors"] = failed
                    st.toast(
                        f"Component import failed: {next(iter(failed.values()))}",
                        icon="⚠️",
                    )
                    with st.expander("Error details", expanded=True):
                        for candidate, error in failed.items():
                            st.markdown(f"- `{candidate}`: {error}")
            except (zipfile.BadZipFile, OSError) as error:
                st.error(f"Could not load the package: {error}")
        if st.session_state.get("ext_component_types"):
            st.caption(
                "Loaded component types: "
                + ", ".join(f"`{t}`" for t in st.session_state["ext_component_types"])
            )

    tabs = st.tabs(
        [
            "🧩 Interfaces",
            "⬇️ Inputs",
            "📁 Staticdata",
            "⬆️ Outputs",
            "🔧 Components",
            "⏱️ Settings",
            "✅ Validation",
            "📤 Export",
            "🌱 ENV",
        ]
    )

    with tabs[0]:
        st.header("Interfaces")
        st.caption(
            "Activate at least one interface. Every entity in inputs/"
            "staticdata/outputs uses exactly one of them. "
            f"{_model_docs_link('interfaces')}"
        )
        for interface in INTERFACES:
            config["interfaces"][interface] = st.checkbox(
                interface.upper(),
                value=config["interfaces"].get(interface, False),
            )

    for tab_pos, section in enumerate(["inputs", "staticdata", "outputs"], start=1):
        with tabs[tab_pos]:
            st.header(section.capitalize())
            st.caption(f"{SECTION_DESCRIPTIONS[section]} {_model_docs_link(section)}")
            if st.button(f"+ Add {section[:-1]}", key=f"add_{section}"):
                config[section].append({"id": "", "attributes": []})
                st.session_state[f"open_{section}"] = len(config[section]) - 1
                st.rerun()
            open_index = st.session_state.get(f"open_{section}")
            for index in range(len(config[section])):
                entity = config[section][index]
                is_open = (
                    index == open_index
                    or len(config[section]) <= 2
                    or (not entity.get("id") and not entity.get("attributes"))
                )
                with st.expander(
                    f"{section[:-1]} {index + 1}: {entity.get('id', '?')}",
                    expanded=is_open,
                ):
                    render_entity(section, index)

    with tabs[4]:
        st.header("Controller Components")
        st.caption(
            "Components perform the calculations. Select a type – the "
            "expected inputs/outputs are loaded automatically from the "
            "component model (identical to service start) and can be "
            "mapped to the entities/attributes from the other tabs. "
            f"[Docs: components]({DOCS_COMPONENTS_URL})"
        )
        if st.button("+ Add component", key="add_component"):
            config["controller_components"].append({"id": "", "type": ""})
            st.session_state["open_component"] = (
                len(config["controller_components"]) - 1
            )
            st.rerun()
        open_component = st.session_state.get("open_component")
        for index in range(len(config["controller_components"])):
            is_open = index == open_component or (
                not config["controller_components"][index].get("id")
                and not config["controller_components"][index].get("type")
            )
            with st.expander(
                f"Component {index + 1}: "
                f"{config['controller_components'][index].get('id', '?')}",
                expanded=is_open,
            ):
                render_component(index)
        if open_component is not None and open_component >= len(
            config["controller_components"]
        ):
            st.session_state.pop("open_component", None)

    with tabs[5]:
        st.header("Controller Settings")
        st.caption(
            f"Time settings for the calculation. {_model_docs_link('calculation')}"
        )
        calculation = config["controller_settings"]["time_settings"].setdefault(
            "calculation", {}
        )
        col1, col2, col3 = st.columns(3)
        calculation["timerange"] = col1.number_input(
            "Timerange",
            min_value=0.0,
            value=float(calculation.get("timerange") or 0),
            step=1.0,
            help="Period the calculation covers (e.g. the last 60 minutes).",
        )
        calculation["timerange_unit"] = col2.selectbox(
            "Timerange unit",
            options=[e.value for e in TimeUnits],
            index=0,
        )
        calculation["timestep"] = col3.number_input(
            "Timestep",
            min_value=0.0,
            value=float(calculation.get("timestep") or 1),
            step=1.0,
            help="Step size of the calculation.",
        )
        calculation["timestep_unit"] = col2.selectbox(
            "Timestep unit",
            options=[e.value for e in TimeUnits],
            index=0,
            key="timestep_unit_sel",
        )
        calculation["sampling_time"] = col1.number_input(
            "Sampling time",
            min_value=0.0,
            value=float(calculation.get("sampling_time") or 1),
            step=1.0,
            help="Sampling time for data acquisition.",
        )
        calculation["sampling_time_unit"] = col3.selectbox(
            "Sampling time unit",
            options=[e.value for e in TimeUnits],
            index=0,
        )

    with tabs[6]:
        st.header("Validation")
        st.caption(
            "Summary of all checks: model validation (identical to "
            "service start) and component wiring. All problems are "
            "listed here with location and description."
        )
        report = check_configuration(config)
        render_report(report)

    with tabs[7]:
        st.header("Export")
        st.caption(
            "The configuration is not saved automatically – export it as "
            "JSON (download) or save it to a path of your choice. The "
            "tool is not connected to a running EnCoDaPy service."
        )
        config["name"] = st.text_input(
            "Configuration name",
            value=config.get("name", "config"),
            help="Used as file name in the export and for documentation "
            "purposes (see docs).",
        )
        export = {key: value for key, value in config.items()}
        json_text = json.dumps(export, indent=2, ensure_ascii=False, default=str)
        st.download_button(
            "⬇️ Download configuration as JSON",
            data=json_text,
            file_name=f"{config.get('name', 'config')}.json",
            mime="application/json",
        )
        with st.expander("JSON preview"):
            st.code(json_text, language="json")
        save_path = st.text_input(
            "Optional: path to save the JSON file",
            help="e.g. /home/user/configs/my_config.json",
        )
        if save_path and st.button("Save file"):
            try:
                with open(save_path, "w", encoding="utf-8") as file:
                    file.write(json_text)
                st.success(f"Saved to {save_path}")
            except OSError as error:
                st.error(f"Saving failed: {error}")

    with tabs[8]:
        st.header("Environment Variables")
        st.caption(
            "Based on the interfaces activated in the configuration, the "
            "following environment variables are required/optional for "
            "the service. Copy the template below into a `.env` file next "
            f"to the service. {_model_docs_link('env')}"
        )
        groups = get_env_requirements(config["interfaces"])
        for group, fields in groups.items():
            st.markdown(f"**{group}**")
            rows = []
            for field in fields:
                required_label = (
                    "yes"
                    if field["required"]
                    else "conditional"
                    if field["condition"]
                    else "no (default)"
                )
                rows.append(
                    {
                        "Variable": field["name"],
                        "Required": required_label,
                        "Default": field["default"],
                        "Condition": field["condition"],
                        "Description": field["description"],
                    }
                )
            st.dataframe(rows, width="stretch", hide_index=True)
        st.subheader("`.env` template")
        template = generate_env_template(config["interfaces"])
        st.code(template, language="dotenv")
        st.download_button(
            "⬇️ Download .env template",
            data=template,
            file_name=".env",
            mime="text/plain",
        )


if __name__ == "__main__":
    main()
