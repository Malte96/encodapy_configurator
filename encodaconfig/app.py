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
import zipfile
from typing import Any

import streamlit as st

from encodaconfig.check import check_configuration
from encodaconfig.components import get_builtin_component_types, get_component_io
from encodaconfig.external import register_zip
from encodapy.config.types import Interfaces
from encodapy.utils.units import TimeUnits

st.set_page_config(page_title="EnCoDaPy Configurator", page_icon="⚙️", layout="wide")


@st.cache_data(show_spinner=False)
def _get_component_io_cached(component_type: str):
    """Cached wrapper: component imports are expensive."""
    if not component_type:
        return None
    try:
        return get_component_io(component_type)
    except (AttributeError, ImportError, KeyError, TypeError):
        return None


DOCS_URL = "https://gewv-tu-dresden.github.io/encodapy/"
DOCS_CONFIG_URL = f"{DOCS_URL}basic_service.html"
DOCS_COMPONENTS_URL = f"{DOCS_URL}components.html"
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
INTERFACE_HELP = {
    "mqtt": f"MQTT Interface – [Doku]({DOCS_URL}interfaces.html)",
    "fiware": f"FIWARE Interface – [Doku]({DOCS_URL}interfaces.html)",
    "file": f"FILE Interface – [Doku]({DOCS_URL}interfaces.html)",
}


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


def render_entity(section: str, index: int) -> None:
    """Render form fields for one entity (input/staticdata/output)."""
    config = st.session_state["config"]
    entities = config[section]
    entity = entities[index]
    col_id, col_iface, col_col = st.columns([3, 2, 1])
    entity["id"] = col_id.text_input(
        f"ID {index + 1}",
        value=entity.get("id", ""),
        key=f"{section}_{index}_id",
        help="Eindeutige ID der Entity (z. B. 'thermal_storage').",
    )
    iface_value = entity.get("interface", "fiware")
    iface_options = [e.value for e in Interfaces]
    entity["interface"] = col_iface.selectbox(
        f"Interface {index + 1}",
        options=iface_options,
        index=iface_options.index(iface_value),
        key=f"{section}_{index}_iface",
        help="Über welches Interface werden die Daten übertragen? "
        "Das Interface muss im Tab 'Interfaces' aktiviert sein.",
    )
    if col_col.button("Delete", key=f"{section}_{index}_del"):
        entities.pop(index)
        st.rerun()
    entity["id_interface"] = st.text_input(
        f"ID interface {index + 1} (leer = ID)",
        value=entity.get("id_interface", ""),
        key=f"{section}_{index}_idiface",
        help="ID der Entity auf dem Interface (FIWARE-Entity-ID, MQTT-Topic …). "
        "Leer lassen, um die ID zu verwenden.",
    )
    attributes = entity.setdefault("attributes", [])
    if st.button(
        f"+ Attribut hinzufügen ({entity['id'] or section})",
        key=f"{section}_{index}_addattr",
    ):
        attributes.append({"id": ""})
        st.rerun()
    for attr_idx, attribute in enumerate(attributes):
        col_a, col_b, col_c = st.columns([3, 3, 1])
        attribute["id"] = col_a.text_input(
            f"Attribut {attr_idx + 1}",
            value=attribute.get("id", ""),
            key=f"{section}_{index}_attr{attr_idx}_id",
            help="Eindeutige ID des Attributs (z. B. 'temperature_1'). "
            "Komponenten referenzieren später genau diese ID.",
        )
        attribute["id_interface"] = col_b.text_input(
            f"Attribut ID interface {attr_idx + 1} (leer = ID)",
            value=attribute.get("id_interface", ""),
            key=f"{section}_{index}_attr{attr_idx}_idiface",
            help="ID des Attributs auf dem Interface (FIWARE-Attributname …).",
        )
        if col_c.button("✕", key=f"{section}_{index}_attr{attr_idx}_del"):
            attributes.pop(attr_idx)
            st.rerun()


def render_component(index: int) -> None:
    """Render form fields for one controller component."""
    config = st.session_state["config"]
    components = config["controller_components"]
    component = components[index]
    component["id"] = st.text_input(
        f"Komponenten-ID {index + 1}",
        value=component.get("id", ""),
        key=f"comp_{index}_id",
        help="Eindeutige ID der Komponente im Controller.",
    )
    component["type"] = st.text_input(
        f"Typ {index + 1}",
        value=component.get("type", ""),
        key=f"comp_{index}_type",
        help="Interner Komponententyp (z. B. 'thermal_storage', "
        "'two_point_controller') oder dotted path für externe Komponenten "
        "(z. B. 'my_package.my_component'). Siehe die Liste der internen "
        "Komponenten in der Sidebar.",
    )
    if st.button("Komponente entfernen", key=f"comp_{index}_del"):
        components.pop(index)
        st.rerun()
    io = (
        _get_component_io_cached(component.get("type", ""))
        if component.get("type")
        else None
    )
    if io is None:
        if component.get("type"):
            st.warning(
                f"Komponententyp '{component['type']}' nicht gefunden "
                "(Modul nicht installierbar oder Name falsch). "
                "Externe Komponenten müssen als Paket installiert sein."
            )
        return
    st.success(
        f"✅ Komponente erkannt – {len(io['inputs'])} Inputs, "
        f"{len(io['outputs'])} Outputs, {len(io['config'])} Config-Felder."
    )
    st.caption(
        "Ordne jedem Feld eine Entity + ein Attribut aus deinen "
        "Inputs/Staticdata/Outputs zu (Dropdowns). Optionale Felder können "
        "leer bleiben – sie werden dann nicht in die Konfiguration "
        "übernommen."
    )
    for direction in ["inputs", "outputs"]:
        expected = io[direction]
        if not expected:
            continue
        allocated = component.setdefault(direction, {})
        st.markdown(
            f"**{direction.capitalize()}** "
            f"({'alle erforderlich' if all(f['required'] for f in expected.values()) else '⚠️ = erforderlich'})"
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
                f"{field_name} → Attribut",
                options=attribute_options,
                index=attribute_options.index(attribute_value)
                if attribute_value in attribute_options
                else 0,
                key=f"comp_{index}_{direction}_{field_name}_attribute",
            )
            col_req.markdown("⚠️ erforderlich" if field_info["required"] else "optional")
    if io["config"]:
        config_fields = component.setdefault("config", {})
        st.markdown("**Config (statische Werte oder Referenzen)**")
        st.caption(
            "Config-Felder sind statische Einstellungen der Komponente: "
            "entweder als direkter Wert (JSON) oder als Referenz auf eine "
            "Entity + Attribut der Staticdata. Nicht benötigte Felder leer "
            "lassen."
        )
        for field_name in io["config"]:
            value = config_fields.get(field_name, "")
            mode = st.radio(
                f"{field_name}: Modus",
                [
                    "nicht gesetzt",
                    "Referenz (Entity + Attribut)",
                    "direkter Wert (JSON)",
                ],
                index=2
                if isinstance(value, dict) and "value" in value
                else 1
                if isinstance(value, dict) and "entity" in value
                else 0,
                key=f"comp_{index}_config_{field_name}_mode",
                horizontal=True,
            )
            if mode == "nicht gesetzt":
                config_fields.pop(field_name, None)
                continue
            if mode == "Referenz (Entity + Attribut)":
                options = datapoint_options(st.session_state["config"])
                entry = value if isinstance(value, dict) and "entity" in value else {}
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
                    f"{field_name} → Attribut",
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
                f'{field_name} → Wert (JSON, z. B. 100, "air" oder {{"a": 1}})',
                value=json.dumps(value["value"])
                if isinstance(value, dict) and "value" in value
                else str(value or ""),
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
    return options


def render_report(report: dict[str, Any]) -> None:
    """Render the validation report in a readable, grouped way."""
    errors: list[dict[str, str]] = report["errors"]
    wiring_issues: list[dict[str, str]] = report["wiring_issues"]
    if not errors and not wiring_issues:
        st.success(
            "✅ **Konfiguration ist valide.** Alle Modellprüfungen und die "
            "Komponenten-Verdrahtung sind erfolgreich – die Konfiguration "
            "kann exportiert und verwendet werden."
        )
        return
    st.subheader("Modellprüfung (Pydantic)")
    st.caption(
        "Diese Fehler stammen direkt aus den EnCoDaPy-Modellen "
        "(`ConfigModel`) – dieselben Prüfungen wie beim Start des Services."
    )
    if errors:
        for err in errors:
            st.error(f"**{err['loc']}** – {err['msg']}")
    else:
        st.markdown("✅ Keine Modellfehler.")
    st.subheader("Komponenten-Verdrautung")
    st.caption(
        "Prüft, ob die zugeordneten Entities/Attribute existieren, alle "
        "erforderlichen Inputs/Outputs zugeordnet sind und keine "
        "unbekannten Zuordnungen vorhanden sind."
    )
    if wiring_issues:
        by_component: dict[str, list[dict[str, str]]] = {}
        for issue in wiring_issues:
            by_component.setdefault(issue["component"], []).append(issue)
        for component_id, issues in by_component.items():
            with st.expander(
                f"🔧 {component_id} ({len(issues)} Probleme)", expanded=True
            ):
                for issue in issues:
                    st.warning(f"{issue['direction']}/{issue['field']}: {issue['msg']}")
    else:
        st.markdown("✅ Keine Verdrahtungsprobleme.")


def main() -> None:
    """Main entry point of the Streamlit app."""
    ensure_state()
    config = st.session_state["config"]

    with st.sidebar:
        st.image(LOGO_URL, width=180)
        st.markdown(
            f"[GEWV / TU Dresden]({GEWV_URL}) · [EnCoDaPy-Doku]({DOCS_URL})",
            unsafe_allow_html=False,
        )
        st.divider()
        st.title("⚙️ EnCoDaPy Configurator")
        st.caption(
            "Visuelle Erstellung und Prüfung von EnCoDaPy-Konfigurationen "
            "auf Basis der vorhandenen Pydantic-Modelle. "
            f"Siehe [Projekt-Doku]({DOCS_URL}) und "
            f"[Komponenten-Doku]({DOCS_COMPONENTS_URL})."
        )
        st.divider()
        st.markdown("#### Bestehende Konfiguration prüfen")
        uploaded = st.file_uploader(
            "JSON-Datei hochladen – wird validiert und kann anschließend "
            "in allen Tabs bearbeitet werden",
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
                st.error(f"Ungültiges JSON: {error}")
        if st.session_state.get("uploaded_name"):
            st.caption(f"Geladen: {st.session_state['uploaded_name']}")
        if st.button("🗑️ Neue (leere) Konfiguration starten"):
            load_config_to_state(new_config())
            st.session_state.pop("uploaded_name", None)
            st.rerun()
        st.divider()
        st.markdown("#### Verfügbare Komponenten")
        st.write(", ".join(get_builtin_component_types()))
        st.divider()
        st.markdown("#### Externe Komponenten einbinden")
        st.caption(
            "Variante 1 (empfohlen, wie beim Service-Start): Paket in der "
            "Umgebung installieren (`pip install bspw_package_components_example`) "
            "und den Typ als dotted path angeben.\n"
            "Variante 2: ZIP/Wheel des Pakets hochladen – es wird für diese "
            "Session importierbar gemacht (kein Schreiben in die Umgebung)."
        )
        ext_upload = st.file_uploader(
            "ZIP oder Wheel eines Komponenten-Pakets",
            type=["zip", "whl"],
            key="ext_upload",
        )
        if ext_upload is not None and ext_upload.name != st.session_state.get(
            "ext_loaded_name"
        ):
            try:
                packages = register_zip(ext_upload.getvalue(), ext_upload.name)
                st.session_state["ext_loaded_name"] = ext_upload.name
                st.session_state["ext_packages"] = packages
                _get_component_io_cached.clear()
                st.success(f"Paket geladen. Top-Level-Pakete: {', '.join(packages)}")
            except (zipfile.BadZipFile, OSError) as error:
                st.error(f"Paket konnte nicht geladen werden: {error}")
        if st.session_state.get("ext_packages"):
            st.caption(
                "Verwende als Komponenten-Typ z. B. `"
                + "` oder `".join(st.session_state["ext_packages"])
                + ".komponentenname``."
            )

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
        st.caption(
            "Aktiviere mindestens ein Interface. Jede Entity in Inputs/"
            "Staticdata/Outputs nutzt genau eines davon. "
            f"[Doku: Konfiguration]({DOCS_CONFIG_URL})"
        )
        for interface in INTERFACES:
            config["interfaces"][interface] = st.checkbox(
                interface.upper(),
                value=config["interfaces"].get(interface, False),
                help=INTERFACE_HELP[interface],
            )

    for tab_pos, section in enumerate(["inputs", "staticdata", "outputs"], start=1):
        with tabs[tab_pos]:
            st.header(section.capitalize())
            st.caption(
                {
                    "inputs": "Eingabedaten des Controllers (z. B. Sensordaten).",
                    "staticdata": "Statische Daten (z. B. Parametrierung von Anlagen).",
                    "outputs": "Ausgabedaten des Controllers (z. B. Rechenergebnisse, Befehle).",
                }[section]
                + f" [Doku]({DOCS_CONFIG_URL})"
            )
            if st.button(f"+ {section[:-1]} hinzufügen", key=f"add_{section}"):
                config[section].append({"id": "", "attributes": []})
                st.rerun()
            for index in range(len(config[section])):
                with st.expander(
                    f"{section[:-1]} {index + 1}: "
                    f"{config[section][index].get('id', '?')}",
                    expanded=len(config[section]) <= 2,
                ):
                    render_entity(section, index)

    with tabs[4]:
        st.header("Controller Components")
        st.caption(
            "Komponenten führen die Berechnungen aus. Wähle einen Typ – die "
            "erwarteten Inputs/Outputs werden automatisch aus dem "
            "Komponenten-Modell geladen (identisch zum Service-Start) und "
            "können hier mit den Entities/Attributen aus den anderen Tabs "
            f"verknüpft werden. [Doku: Komponenten]({DOCS_COMPONENTS_URL})"
        )
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
        st.caption(
            "Zeiteinstellungen für die Berechnung. Details in der "
            f"[Doku]({DOCS_CONFIG_URL})."
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
            help="Zeitraum, für den gerechnet wird (z. B. 60 Minuten zurück).",
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
            help="Schrittweite der Berechnung.",
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
            help="Abtastzeit für die Datenaufnahme.",
        )
        calculation["sampling_time_unit"] = col3.selectbox(
            "Sampling Time Einheit",
            options=[e.value for e in TimeUnits],
            index=0,
        )

    with tabs[6]:
        st.header("Prüfung")
        st.caption(
            "Zusammenfassung aller Prüfungen: Modellvalidierung "
            "(identisch zum Service-Start) und Komponenten-Verdrautung. "
            "Alle Probleme werden hier mit Ort und Beschreibung aufgelistet."
        )
        report = check_configuration(config)
        render_report(report)

    with tabs[7]:
        st.header("Export")
        st.caption(
            "Die Konfiguration wird nicht automatisch gespeichert – exportiere "
            "sie als JSON (Download) oder speichere sie auf einem Pfad deiner "
            "Wahl. Das Tool ist nicht mit einem laufenden EnCoDaPy-Service "
            "verbunden."
        )
        export = {key: value for key, value in config.items() if key != "name"}
        export["name"] = config.get("name", "config")
        json_text = json.dumps(export, indent=2, ensure_ascii=False, default=str)
        st.download_button(
            "⬇️ Konfiguration als JSON herunterladen",
            data=json_text,
            file_name=f"{config.get('name', 'config')}.json",
            mime="application/json",
        )
        with st.expander("JSON-Vorschau"):
            st.code(json_text, language="json")
        save_path = st.text_input(
            "Optional: Pfad zum Abspeichern der JSON-Datei",
            help="z. B. /home/user/configs/my_config.json",
        )
        if save_path and st.button("Datei speichern"):
            try:
                with open(save_path, "w", encoding="utf-8") as file:
                    file.write(json_text)
                st.success(f"Gespeichert unter {save_path}")
            except OSError as error:
                st.error(f"Speichern fehlgeschlagen: {error}")


if __name__ == "__main__":
    main()
