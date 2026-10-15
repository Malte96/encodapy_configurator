"""Tests for the encodaconfig core modules (validation, components, check).

These tests are pure unit tests: no network, no running EnCoDaPy service
and no Streamlit runtime is required.
"""

import json
from pathlib import Path

from encodaconfig import (
    check_configuration,
    get_builtin_component_types,
    get_component_io,
    validate_config,
)
from encodaconfig.check import check_component_wiring
from encodaconfig.validation import format_errors, validate_config_file

REPO_ROOT = Path(__file__).parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "examples" / "01_config" / "config.json"


def load_example_config() -> dict:
    """Load the example configuration from the repository."""
    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as file:
        return json.load(file)


def base_config() -> dict:
    """Minimal valid configuration with one fiware input and output."""
    return {
        "name": "test",
        "interfaces": {"mqtt": False, "fiware": True, "file": False},
        "inputs": [
            {
                "id": "input_01",
                "interface": "fiware",
                "attributes": [{"id": "temperature_1", "type": "timeseries"}],
            }
        ],
        "outputs": [
            {
                "id": "output_01",
                "interface": "fiware",
                "attributes": [{"id": "state_of_charge", "type": "value"}],
            }
        ],
        "staticdata": [],
        "controller_components": [],
        "controller_settings": {
            "time_settings": {
                "calculation": {"timerange": 60, "timerange_unit": "minute"}
            }
        },
    }


class TestValidation:
    """Tests for the model validation (reuses encodapy ConfigModel)."""

    def test_valid_config(self):
        report = validate_config(load_example_config())
        assert report["valid"] is True
        assert report["errors"] == []
        assert report["model"] is not None

    def test_invalid_config_missing_interfaces(self):
        config = base_config()
        config["interfaces"] = {"mqtt": False, "fiware": False, "file": False}
        report = validate_config(config)
        assert report["valid"] is False
        assert any("interface" in err["msg"].lower() for err in report["errors"])

    def test_invalid_config_interface_not_active(self):
        config = base_config()
        config["interfaces"]["fiware"] = False
        report = validate_config(config)
        assert report["valid"] is False
        assert report["errors"]

    def test_invalid_config_missing_settings(self):
        config = base_config()
        del config["controller_settings"]
        report = validate_config(config)
        assert report["valid"] is False
        assert any(
            err["loc"].startswith("controller_settings") for err in report["errors"]
        )

    def test_config_file_validation(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(base_config()), encoding="utf-8")
        report = validate_config_file(str(config_path))
        assert report["valid"] is True

    def test_config_file_not_found(self, tmp_path):
        report = validate_config_file(str(tmp_path / "missing.json"))
        assert report["valid"] is False
        assert report["errors"][0]["type"] == "file_error"

    def test_format_errors(self):
        formatted = format_errors(
            [{"loc": "inputs.0.id", "msg": "Field required", "type": "missing"}]
        )
        assert "[inputs.0.id] Field required" in formatted


class TestComponents:
    """Tests for the component introspection via the encodapy loader."""

    def test_builtin_components_listed(self):
        types = get_builtin_component_types()
        assert "thermal_storage" in types
        assert "two_point_controller" in types
        assert "weather_data" in types

    def test_known_component_io(self):
        io = get_component_io("two_point_controller")
        assert io is not None
        assert io["available"] is True
        assert "current_value" in io["inputs"]
        assert io["inputs"]["current_value"]["required"] is True
        assert "control_signal" in io["outputs"]

    def test_unknown_component_returns_none(self):
        assert get_component_io("does_not_exist_component") is None


class TestCheck:
    """Tests for the full check incl. component wiring."""

    def test_example_config_reports_removed_component_type(self):
        """The example config uses the legacy type 'storage_controller'.

        The wiring check must report this type as not importable instead of
        crashing - identical to the behavior at component start.
        """
        report = check_configuration(load_example_config())
        assert report["valid"] is False
        assert any(
            issue["field"] == "type" and "storage_controller" in issue["msg"]
            for issue in report["wiring_issues"]
        )

    def test_wiring_missing_entity(self):
        config = base_config()
        config["controller_components"] = [
            {
                "id": "controller_01",
                "type": "two_point_controller",
                "inputs": {
                    "current_value": {
                        "entity": "does_not_exist",
                        "attribute": "temperature_1",
                    },
                    "latest_control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    },
                },
                "outputs": {
                    "control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    }
                },
            }
        ]
        issues = check_component_wiring(config)
        assert any("not defined in" in issue["msg"] for issue in issues)

    def test_wiring_required_input_missing(self):
        config = base_config()
        config["controller_components"] = [
            {
                "id": "controller_01",
                "type": "two_point_controller",
                "inputs": {
                    "latest_control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    }
                },
                "outputs": {
                    "control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    }
                },
            }
        ]
        issues = check_component_wiring(config)
        assert any(
            "current_value" in issue["msg"] and "not allocated" in issue["msg"]
            for issue in issues
        )

    def test_wiring_unknown_allocation(self):
        config = base_config()
        config["controller_components"] = [
            {
                "id": "controller_01",
                "type": "two_point_controller",
                "inputs": {
                    "current_value": {
                        "entity": "input_01",
                        "attribute": "temperature_1",
                    },
                    "latest_control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    },
                    "unexpected_field": {
                        "entity": "input_01",
                        "attribute": "temperature_1",
                    },
                },
                "outputs": {
                    "control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    }
                },
            }
        ]
        issues = check_component_wiring(config)
        assert any("unexpected_field" in issue["msg"] for issue in issues)

    def test_wiring_unknown_component_type(self):
        config = base_config()
        config["controller_components"] = [
            {
                "id": "controller_01",
                "type": "unknown_type_xyz",
                "inputs": {},
                "outputs": {},
            }
        ]
        issues = check_component_wiring(config)
        assert any("not found" in issue["msg"] for issue in issues)
        report = check_configuration(config)
        assert report["valid"] is False

    def test_wiring_valid_two_point_controller(self):
        config = base_config()
        config["controller_components"] = [
            {
                "id": "controller_01",
                "type": "two_point_controller",
                "inputs": {
                    "current_value": {
                        "entity": "input_01",
                        "attribute": "temperature_1",
                    },
                    "latest_control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    },
                },
                "outputs": {
                    "control_signal": {
                        "entity": "output_01",
                        "attribute": "state_of_charge",
                    }
                },
            }
        ]
        report = check_configuration(config)
        assert report["wiring_issues"] == []
        assert report["valid"] is True


class TestStreamlitAppImportable:
    """Smoke test: the app module must be importable (no Streamlit runtime needed)."""

    def test_app_module_importable(self):
        import streamlit  # noqa: F401  # ensures the dependency is installed

        from encodaconfig import app  # noqa: F401  # import must not execute the UI


class TestExternalComponents:
    """Tests for runtime registration of external component packages."""

    def test_register_zip(self, tmp_path):
        import zipfile

        from encodaconfig.external import loaded_paths, register_zip

        pkg_dir = tmp_path / "bspw_pkg"
        (pkg_dir / "sub").mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "sub" / "__init__.py").write_text("")
        zip_path = tmp_path / "pkg.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.write(pkg_dir / "__init__.py", "bspw_pkg/__init__.py")
            archive.write(pkg_dir / "sub" / "__init__.py", "bspw_pkg/sub/__init__.py")
        packages = register_zip(zip_path.read_bytes(), "pkg.zip")
        assert "bspw_pkg" in packages
        assert any("encodaconfig_ext_" in p for p in loaded_paths())


class TestEnvRequirements:
    """Tests for the ENV requirements introspection."""

    def test_fiware_env_required_variables(self):
        from encodaconfig.env_requirements import get_env_requirements

        groups = get_env_requirements({"mqtt": False, "fiware": True, "file": False})
        assert any("fiware" in key for key in groups)
        fiware_fields = groups["fiware (FIWARE_ prefix)"]
        required = {f["name"] for f in fiware_fields if f["required"]}
        assert "FIWARE_SERVICE" in required
        assert "FIWARE_CB_URL" not in required  # has a default

    def test_inactive_interfaces_not_listed(self):
        from encodaconfig.env_requirements import get_env_requirements

        groups = get_env_requirements({"mqtt": False, "fiware": False, "file": True})
        assert not any("fiware" in key for key in groups)
        assert not any("mqtt" in key for key in groups)
        assert any("file" in key for key in groups)

    def test_env_template_generation(self):
        from encodaconfig.env_requirements import generate_env_template

        template = generate_env_template({"mqtt": True, "fiware": True, "file": False})
        assert template.startswith("# .env template")
        assert "FIWARE_SERVICE=" in template  # required: uncommented
        assert "# MQTT_HOST=127.0.0.1" in template  # optional: commented


class TestExternalComponentDetection:
    """Tests for automatic detection of components in uploaded ZIPs."""

    def _make_component_zip(self, tmp_path, valid: bool = True):
        import zipfile

        pkg = tmp_path / "local_controller_substation"
        comp = pkg / "substation_controller"
        comp.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (comp / "__init__.py").write_text("")
        config_content = (
            "from typing import Optional\n"
            "from encodapy.components.basic_component_config import "
            "ConfigData, InputData, OutputData\n"
            "from encodapy.utils.datapoints import DataPointGeneral\n\n\n"
            "class SubstationControllerInputData(InputData):\n"
            "    current_value: DataPointGeneral\n\n\n"
            "class SubstationControllerOutputData(OutputData):\n"
            "    control_signal: Optional[DataPointGeneral] = None\n"
        )
        if valid:
            (comp / "substation_controller_config.py").write_text(config_content)
        zip_path = tmp_path / "substation.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.write(
                pkg / "__init__.py", "local_controller_substation/__init__.py"
            )
            archive.write(
                comp / "__init__.py",
                "local_controller_substation/substation_controller/__init__.py",
            )
            if valid:
                archive.write(
                    comp / "substation_controller_config.py",
                    "local_controller_substation/substation_controller/"
                    "substation_controller_config.py",
                )
        return zip_path

    def test_find_component_candidates(self, tmp_path):
        from encodaconfig.external import (
            find_component_candidates,
            register_zip,
            loaded_paths,
        )

        zip_path = self._make_component_zip(tmp_path)
        register_zip(zip_path.read_bytes(), "substation.zip")
        candidates = find_component_candidates(loaded_paths()[-1])
        assert candidates == ["local_controller_substation.substation_controller"]

    def test_find_component_types_verified(self, tmp_path):
        from encodaconfig.external import (
            find_component_types,
            loaded_paths,
            register_zip,
        )

        zip_path = self._make_component_zip(tmp_path)
        register_zip(zip_path.read_bytes(), "substation.zip")
        assert find_component_types(loaded_paths()) == [
            "local_controller_substation.substation_controller"
        ]

    def test_no_components_found_for_plain_zip(self, tmp_path):
        from encodaconfig.external import (
            find_component_candidates,
            register_zip,
            loaded_paths,
        )

        zip_path = self._make_component_zip(tmp_path, valid=False)
        register_zip(zip_path.read_bytes(), "plain.zip")
        assert find_component_candidates(loaded_paths()[-1]) == []


class TestEmptyComponentType:
    """Newly added components have an empty type and must not trigger
    loader lookups or issues."""

    def test_empty_type_component_is_skipped(self):
        from encodaconfig.check import check_component_wiring
        from encodaconfig import check_configuration

        config = {
            "interfaces": {"mqtt": False, "fiware": True, "file": False},
            "inputs": [],
            "outputs": [],
            "staticdata": [],
            "controller_components": [
                {"id": "new_comp", "type": ""},
                {"id": "", "type": ""},
            ],
            "controller_settings": {
                "time_settings": {"calculation": {"timerange": 60}}
            },
        }
        assert check_component_wiring(config) == []
        report = check_configuration(config)
        assert report["wiring_issues"] == []
