# encodaconfig

Visuelles Tool zur **Erstellung und Prüfung** von EnCoDaPy-Konfigurationen
(JSON) im Browser. Das Tool ist ein eigener, leichtgewichtiger Subfolder und
ist **nicht** mit einem laufenden EnCoDaPy-Service verbunden.

## Umgebung (Poetry)

Das Tool hat eine **eigene Poetry-Umgebung** (unabhängig von der
EnCoDaPy-Hauptumgebung), damit Streamlit und seine transitiven Abhängigkeiten
keine Konflikte mit dem Hauptpaket verursachen. `encodapy` selbst wird per
Path-Dependency eingebunden:

```toml
# encodaconfig/pyproject.toml (Auszug)
encodapy = { path = "..", develop = true }
streamlit = ">=1.40"
```

Installation und Start:

```bash
cd encodaconfig
poetry install
poetry run streamlit run app.py
```

Die App läuft lokal im Browser (`http://localhost:8501`).

Tests laufen aus der Sub-Umgebung ebenfalls (das Hauptpaket ist ja per
Path eingebunden):

```bash
cd encodaconfig
poetry run pytest ../tests/encodaconfig -q
```

## Start (alternativ ohne Poetry)

```bash
pip install streamlit
streamlit run encodaconfig/app.py
```

## Funktionsweise

Das Tool nutzt konsequent die vorhandenen Modelle und Loader des
`encodapy`-Pakets – es wird keine eigene Modell-/Validierungslogik
dupliziert. Dadurch sind neue Komponenten und Modelländerungen im
Hauptpaket automatisch im Tool verfügbar, ohne zusätzliche Anpassungen:

| Aufgabe | Verwendete EnCoDaPy-Bausteine |
|---|---|
| Formularstruktur / Validierung | `encodapy.config.models.ConfigModel` (Pydantic v2, inkl. aller `model_validator`-Prüfungen wie `check_interfaces`, Timerange-Checks) |
| Komponenten-Inputs/-Outputs ermitteln | `encodapy.components.component_loader` (`get_component_input_data_model`, `get_component_output_data_model`, `get_component_config_data_model`) – dieselben Funktionen wie beim Start der Komponenten |
| Externe Komponenten | dotted-path `type` (z. B. `my_package.my_component`), bereits von `check_component_type()` unterstützt |

### Kernmodule (ohne Streamlit nutzbar)

```python
from encodaconfig import check_configuration, get_component_io, validate_config

report = check_configuration(config_dict)
report["valid"]  # Gesamturteil
report["errors"]  # Modellfehler (Pfad + Meldung)
report["wiring_issues"]  # Komponenten-IO-Probleme (Entity/Attribute fehlen,
# erforderliche Inputs nicht zugeordnet,
# unerwartete Zuordnungen, unbekannter Typ)
```

`get_component_io("two_point_controller")` liefert die erwarteten
Inputs/Outputs inkl. Pflichtfeldern und Beschreibungen; für nicht
installierte/externe Typen wird `None` zurückgegeben.

### Prüfungen im Detail

1. **Modellprüfung** – die Config wird gegen `ConfigModel` validiert
   (identisch zum Service-Start, inkl. Interface- und Timerange-Validatoren).
2. **Komponenten-IO-Prüfung** – für jede `controller_component` wird der Typ
   über den Component-Loader aufgelöst und geprüft:
   - Sind zugeordnete `entity`/`attribute` in `inputs`/`staticdata`/`outputs` definiert?
   - Sind alle erforderlichen Inputs/Outputs der Komponente zugeordnet?
   - Gibt es Zuordnungen zu Feldern, die die Komponente gar nicht hat?

### Export

Keine statische Speicherung: Die Config liegt im Session-State der App und
kann als **JSON heruntergeladen** oder optional auf einem angegebenen Pfad
gespeichert werden.

## Tests

```bash
pytest tests/encodaconfig -v
```

Die Tests decken Modellvalidierung, Komponenten-Introspektion und die
Komponenten-Verdrahtungsprüfung ab (reine Unit-Tests, keine externen
Abhängigkeiten).
