# encodaconfig

Visual tool for **creating and validating** EnCoDaPy configurations (JSON)
in the browser. The tool is a separate, lightweight subfolder and is
**not** connected to a running EnCoDaPy service.

## Environment (Poetry)

The tool has its **own Poetry environment** (independent of the main
EnCoDaPy environment), so that Streamlit and its transitive dependencies
do not cause conflicts with the main package. `encodapy` itself is
included as a path dependency:

```toml
# encodaconfig/pyproject.toml (excerpt)
encodapy = { path = "..", develop = true }
streamlit = ">=1.40"
```

Installation and start:

```bash
cd encodaconfig
poetry install
poetry run streamlit run app.py
```

The app runs locally in the browser (`http://localhost:8501`).

Tests also run from the sub-environment (the main package is included
via the path dependency):

```bash
cd encodaconfig
poetry run pytest ../tests/encodaconfig -q
```

## Start (alternative, without Poetry)

```bash
pip install streamlit
streamlit run encodaconfig/app.py
```

## How it works

The tool consistently reuses the existing models and loaders of the
`encodapy` package – no model or validation logic is duplicated. As a
result, new components and model changes in the main package are
automatically available in the tool without further adaptations:

| Task | EnCoDaPy building blocks used |
|---|---|
| Form structure / validation | `encodapy.config.models.ConfigModel` (Pydantic v2, including all `model_validator` checks such as `check_interfaces`, timerange checks) |
| Component inputs/outputs | `encodapy.components.component_loader` (`get_component_input_data_model`, `get_component_output_data_model`, `get_component_config_data_model`) – the same functions used at component start |
| External components | dotted-path `type` (e.g. `my_package.my_component`), already supported by `check_component_type()`; additionally uploadable as ZIP/wheel for the session |
| Environment variables | `encodapy.config.env_values` (pydantic-settings models), introspected for the ENV tab |

### Core modules (usable without Streamlit)

```python
from encodaconfig import check_configuration, get_component_io, validate_config

report = check_configuration(config_dict)
report["valid"]  # overall verdict
report["errors"]  # model errors (path + message)
report["wiring_issues"]  # component IO problems (missing entity/attribute,
# required inputs not allocated,
# unexpected mappings, unknown type)
```

`get_component_io("two_point_controller")` returns the expected
inputs/outputs including required flags and descriptions; for
non-installed/external types `None` is returned.

### Checks in detail

1. **Model validation** – the config is validated against `ConfigModel`
   (identical to service start, including the interface and timerange
   validators).
2. **Component wiring check** – for every `controller_component` the type
   is resolved via the component loader and checked:
   - Are the mapped `entity`/`attribute` defined in
     `inputs`/`staticdata`/`outputs`?
   - Are all required inputs/outputs of the component allocated?
   - Are there mappings to fields the component does not have?

### UI overview

- **Validate existing configuration:** upload a JSON file in the
  sidebar – it is validated immediately and can then be edited in all
  tabs.
- **Create new configuration:** start with an empty configuration and
  work through the tabs (Interfaces → Inputs/Staticdata/Outputs →
  Components → Settings).
- **Components tab:** the component type is selected via a searchable
  dropdown; the expected inputs/outputs are loaded automatically from
  the component model and can be mapped to entities/attributes via
  dropdowns. Config fields support direct values (JSON) or references.
- **ENV tab:** shows which environment variables are required/optional
  for the interfaces activated in the configuration (introspected from
  `encodapy.config.env_values`) and generates a copyable `.env`
  template including a download button.
- **External components:** either install the package in the
  environment (recommended, as at service start) or upload its ZIP/wheel
  in the sidebar – the package is made importable for the session
  without writing to the environment. Loading code from URLs is
  deliberately not supported for security and reproducibility reasons.

### Export

No static storage: the configuration lives in the session state of the
app and can be **downloaded as JSON** or optionally saved to a path of
your choice. The tool is not connected to a running EnCoDaPy service.

## Tests

```bash
pytest tests/encodaconfig -v
```

The tests cover model validation, component introspection, the
component wiring check and the ENV requirements (pure unit tests, no
external dependencies).
