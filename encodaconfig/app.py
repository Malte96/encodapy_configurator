"""
Streamlit web UI for creating and validating EnCoDaPy configurations.

Run with:

    streamlit run encodaconfig/app.py

The app is a thin layer over the core modules (validation, components,
check): the configuration is held in the Streamlit session state, can be
exported as JSON (download or optional file path) and is not connected
to a running EnCoDaPy service.
"""

import json
from typing import Any, Dict, List

import streamlit as st

from encodapy.config.types import Interfaces
from encodapy.utils.units import TimeUnits

from encodaconfig.check import check_configuration
from encodaconfig.components import get_builtin_component_types, get_component_io
from encodaconfig.validation import format_errors

st.set_page_config(page_title="EnCoDaPy Configurator", page_icon="⚙️", layout="wide")

INTERFACES = ["mqtt", "fiware", "file"]
ENTITY_SECTIONS = {
    "inputs": "input",
    "staticdata": "staticdata",
    "outputs": "output",
}


def new_config() -> Dict[str, Any]:
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


def load_config_to_state(config: Dict[str, Any]) -> None:
    """Put a configuration dict into the session state (normalized)."""
    base = new_config()
    for key, value in config.items():
        base[key] = value
    st.session_state["config"] = base
    for section in ENTITY_SECTIONS:
        st.session_state[f"{section}_count"] = len(base.get(section, []))
    st.session_state["components_count"] = len(base.get("controller_components", []))


def ensure_state() -> None:
    """Initialize the session state if not present."""
    if "config" not in st.session_state:
        load_config_to_state(new_config())
        st.session_state.setdefault("components_count", 0)
        for section in ENTITY_SECTIONS:
            st.session_state.setdefault(f"{section}_count", 0)


def render_entity(section: str, index: int) -> None:
    """Render form fields for one entity (input/staticdata/output)."""
    config = st.session_state["config"]
    entities = config[section]
    entity = entities[index] if index < len(entities) else {"id": "", "attributes": []}
    col_id, col_iface, col_col = st.columns([3, 2, 1])
    entity["id"] = col_id.text_input(
        f"ID {index + 1}", value=entity.get("id", ""), key=f"{section}_{index}_id"
    )
    iface_value = entity.get("interface", "fiware")
    entity["interface"] = col_iface.selectbox(
        f"Interface {index + 1}",
        options=[e.value for e in Interfaces],
        index=[e.value for e in Interfaces].index(iface_value),
        key=f"{section}_{index}_iface",
    )
    if col_col.button("Delete", key=f"{section}_{index}_del"):
        entities.pop(index)
        st.session_state[f"{section}_count"] -= 1
        st.rerun()
    entity["id_interface"] = st.text_input(
        f"ID interface {index + 1} (empty = ID)",
        value=entity.get("id_interface", ""),
        key=f"{section}_{index}_idiface",
    )
    attributes = entity.setdefault("attributes", [])
    if st.button(
        f"+ Attribut ({entity['id'] or section})", key=f"{section}_{index}_addattr"
    ):
        attributes.append({"id": ""})
        st.rerun()
    for attr_idx, attribute in enumerate(attributes):
        col_a, col_b, col_c = st.columns([3, 3, 1])
        attribute["id"] = col_a.text_input(
            f"Attribut {attr_idx + 1}",
            value=attribute.get("id", ""),
            key=f"{section}_{index}_attr{attr_idx}_id",
        )
        attribute["id_interface"] = col_b.text_input(
            f"Attribut ID interface {attr_idx + 1} (leer = ID)",
            value=attribute.get("id_interface", ""),
            key=f"{section}_{index}_attr{attr_idx}_idiface",
        )
        if col_c.button("✕", key=f"{section}_{index}_attr{attr_idx}_del"):
            attributes.pop(attr_idx)
            st.rerun()


def render_component(index: int) -> None:
    """Render form fields for one controller component."""
    config = st.session_state["config"]
    components = config["controller_components"]
    component = components[index] if index < len(components) else {}
    component["id"] = st.text_input(
        f"Komponenten-ID {index + 1}",
        value=component.get("id", ""),
        key=f"comp_{index}_id",
    )
    component["type"] = st.text_input(
        f"Typ {index + 1} (interner Name oder dotted path für externe Komponenten)",
        value=component.get("type", ""),
        key=f"comp_{index}_type",
    )
    if st.button("Komponente entfernen", key=f"comp_{index}_del"):
        components.pop(index)
        st.rerun()
    io = get_component_io(component.get("type", "")) if component.get("type") else None
    if io is None:
        if component.get("type"):
            st.warning(
                f"Komponententyp '{component['type']}' nicht gefunden "
                "(Modul nicht importierbar)."
            )
        return
    st.success(
        f"Komponente erkannt. Inputs: {list(io['inputs'])}, Outputs: {list(io['outputs'])}"
    )
    for direction in ["inputs", "outputs"]:
        expected = io[direction]
        if not expected:
            continue
        allocated = component.setdefault(direction, {})
        st.markdown(f"**{direction.capitalize()}**")
        for field_name, field_info in expected.items():
            if field_name not in allocated:
                allocated[field_name] = {"entity": "", "attribute": ""}
            options = datapoint_options(st.session_state["config"])
            current = allocated[field_name]
            col_e, col_a, col_req = st.columns([3, 3, 2])
            entity_options = [""] + list(options)
            entity_value = current.get("entity", "")
            if entity_value not in entity_options:
                entity_options.append(entity_value)
            current["entity"] = col_e.selectbox(
                f"{field_name} → Entity",
                options=entity_options,
                index=entity_options.index(entity_value) if entity_value else 0,
                key=f"comp_{index}_{direction}_{field_name}_entity",
            )
            attribute_options = [""] + list(
                options.get(current["entity"], {}).get("attributes", {})
            )
            attribute_value = current.get("attribute", "")
            if attribute_value not in attribute_options:
                attribute_options.append(attribute_value)
            current["attribute"] = col_a.selectbox(
                f"{field_name} → Attribut",
                options=attribute_options,
                index=attribute_options.index(attribute_value)
                if attribute_value in attribute_options
                else 0,
                key=f"comp_{index}_{direction}_{field_name}_attribute",
            )
            col_req.markdown("⚠️ erforderlich" if field_info["required"] else "optional")
            if field_info.get("description"):
                st.caption(field_info["description"])
    if io["config"]:
        config_fields = component.setdefault("config", {})
        st.markdown("**Config**")
        for field_name in io["config"]:
            config_fields.setdefault(field_name, None)


def datapoint_options(config: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    """Build the selectable entity/attribute options from the config."""
    options: Dict[str, Dict[str, List[str]]] = {}
    for section in ENTITY_SECTIONS:
        for entity in config.get(section, []) or []:
            if not entity.get("id"):
                continue
            entry = options.setdefault(entity["id"], {"attributes": {}, "sections": []})
            entry["sections"].append(section)
            for attribute in entity.get("attributes", []) or []:
                if attribute.get("id"):
                    entry["attributes"].setdefault(attribute["id"], section)
    return options


def main() -> None:
    """Main entry point of the Streamlit app."""
    ensure_state()
    config = st.session_state["config"]

    with st.sidebar:
        st.title("⚙️ EnCoDaPy Configurator")
        st.caption(
            "Visuelle Erstellung und Prüfung von EnCoDaPy-Konfigurationen "
            "auf Basis der vorhandenen Pydantic-Modelle."
        )
        uploaded = st.file_uploader(
            "Bestehende Konfiguration laden (JSON)", type="json"
        )
        if uploaded is not None:
            try:
                load_config_to_state(json.load(uploaded))
                st.success("Konfiguration geladen.")
            except json.JSONDecodeError as error:
                st.error(f"Ungültiges JSON: {error}")
        if st.button("Neue Konfiguration"):
            load_config_to_state(new_config())
        st.divider()
        st.markdown("**Interne Komponenten**")
        st.write(", ".join(get_builtin_component_types()))

    tabs = st.tabs(
        [
            "🧩 Interfaces",
            "⬇️ Inputs",
            "📁 Staticdata",
            "⬆️ Outputs",
            "🔧 Komponenten",
            "⏱️ Settings",
            "✅ Prüfung",
            "📤 Export",
        ]
    )

    with tabs[0]:
        st.header("Interfaces")
        for interface in INTERFACES:
            config["interfaces"][interface] = st.checkbox(
                interface.upper(), value=config["interfaces"].get(interface, False)
            )

    for tab_pos, section in enumerate(["inputs", "staticdata", "outputs"], start=1):
        with tabs[tab_pos]:
            st.header(section.capitalize())
            if st.button(f"+ {section[:-1]} hinzufügen", key=f"add_{section}"):
                config[section].append({"id": "", "attributes": []})
                st.rerun()
            for index in range(len(config[section])):
                st.subheader(f"{section[:-1]} {index + 1}")
                render_entity(section, index)

    with tabs[4]:
        st.header("Controller Components")
        if st.button("+ Komponente hinzufügen", key="add_component"):
            config["controller_components"].append({"id": "", "type": ""})
            st.rerun()
        for index in range(len(config["controller_components"])):
            with st.expander(
                f"Komponente {index + 1}: "
                f"{config['controller_components'][index].get('id', '?')}"
            ):
                render_component(index)

    with tabs[5]:
        st.header("Controller Settings")
        calculation = config["controller_settings"]["time_settings"].setdefault(
            "calculation", {}
        )
        col1, col2, col3 = st.columns(3)
        calculation["timerange"] = col1.number_input(
            "Timerange",
            min_value=0.0,
            value=float(calculation.get("timerange") or 0),
            step=1.0,
        )
        calculation["timerange_unit"] = col2.selectbox(
            "Timerange Einheit",
            options=[e.value for e in TimeUnits],
            index=0,
        )
        calculation["timestep"] = col3.number_input(
            "Timestep",
            min_value=0.0,
            value=float(calculation.get("timestep") or 1),
            step=1.0,
        )
        calculation["timestep_unit"] = col2.selectbox(
            "Timestep Einheit",
            options=[e.value for e in TimeUnits],
            index=0,
            key="timestep_unit_sel",
        )
        calculation["sampling_time"] = col1.number_input(
            "Sampling Time",
            min_value=0.0,
            value=float(calculation.get("sampling_time") or 1),
            step=1.0,
        )
        calculation["sampling_time_unit"] = col3.selectbox(
            "Sampling Time Einheit",
            options=[e.value for e in TimeUnits],
            index=0,
        )

    with tabs[6]:
        st.header("Prüfung")
        report = check_configuration(config)
        if report["valid"] and not report["wiring_issues"]:
            st.success("✅ Konfiguration ist valide (Modelle und Komponenten-IO).")
        else:
            if report["errors"]:
                st.error("Modellfehler:")
                st.code(format_errors(report["errors"]), language="text")
            for issue in report["wiring_issues"]:
                st.warning(
                    f"Komponente '{issue['component']}' / {issue['direction']}"
                    f" '{issue['field']}': {issue['msg']}"
                )

    with tabs[7]:
        st.header("Export")
        export = {key: value for key, value in config.items() if key != "name"}
        export["name"] = config.get("name", "config")
        json_text = json.dumps(export, indent=2, ensure_ascii=False, default=str)
        st.download_button(
            "Konfiguration als JSON herunterladen",
            data=json_text,
            file_name=f"{config.get('name', 'config')}.json",
            mime="application/json",
        )
        st.text_area("JSON (Vorschau)", value=json_text, height=300)
        save_path = st.text_input("Optional: Pfad zum Abspeichern der JSON-Datei")
        if save_path and st.button("Datei speichern"):
            try:
                with open(save_path, "w", encoding="utf-8") as file:
                    file.write(json_text)
                st.success(f"Gespeichert unter {save_path}")
            except OSError as error:
                st.error(f"Speichern fehlgeschlagen: {error}")


if __name__ == "__main__":
    main()
