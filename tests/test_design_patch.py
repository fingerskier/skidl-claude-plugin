"""Phase C tests: declarative design patches (apply_design_patch + schema)."""

import pytest
from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, nets, project_io
from skidl_mcp.tools.design_patch import (
    DesignPatch,
    NetPatch,
    PartPatch,
    PatchError,
    validate_patch,
)


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


class TestSchema:
    def test_from_dict_builds_typed_patch(self):
        p = DesignPatch.from_obj({
            "parts": [{"ref": "R1", "lib": "Device", "name": "R", "value": "10k",
                       "role": "pullup", "fields": {"Tol": "1%"}}],
            "nets": [{"name": "SDA", "role": "i2c_data", "pins": ["U1.SDA", "R1.1"],
                      "pins_mode": "set"}],
            "interfaces": [{"name": "i2c0", "type": "i2c", "nets": {"sda": "SDA"}}],
            "remove_parts": ["R9"],
            "remove_nets": ["OLD"],
            "disconnect": ["R2.2"],
        })
        assert isinstance(p.parts[0], PartPatch)
        assert p.parts[0].ref == "R1" and p.parts[0].value == "10k"
        assert p.parts[0].fields == {"Tol": "1%"}
        assert isinstance(p.nets[0], NetPatch)
        assert p.nets[0].pins == ["U1.SDA", "R1.1"] and p.nets[0].pins_mode == "set"
        assert p.interfaces[0].nets == {"sda": "SDA"}
        assert p.remove_parts == ["R9"] and p.disconnect == ["R2.2"]

    def test_from_yaml_string(self):
        p = DesignPatch.from_obj(
            "parts:\n  - ref: R1\n    lib: Device\n    name: R\n"
            "nets:\n  - name: GND\n    pins: [R1.2]\n"
        )
        assert p.parts[0].ref == "R1"
        assert p.nets[0].name == "GND" and p.nets[0].pins == ["R1.2"]

    def test_empty_patch_is_valid_and_empty(self):
        p = DesignPatch.from_obj({})
        assert p.parts == [] and p.nets == [] and p.remove_parts == []
        p2 = DesignPatch.from_obj(None)
        assert p2.parts == []

    def test_defaults_applied(self):
        p = DesignPatch.from_obj({"nets": [{"name": "N1"}]})
        assert p.nets[0].pins == [] and p.nets[0].pins_mode == "add" and p.nets[0].role == ""

    def test_non_mapping_raises_patch_error(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj([1, 2, 3])

    def test_bad_yaml_raises_patch_error(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj("parts: [unclosed")

    def test_part_without_ref_raises(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj({"parts": [{"lib": "Device", "name": "R"}]})

    def test_bad_pins_mode_raises(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj({"nets": [{"name": "N", "pins_mode": "wipe"}]})


def _two_resistors():
    """Active circuit with bare R1, R2 (pins 1 & 2). Offline-safe."""
    circuit.create_circuit("c")
    entry = manager.get_active()
    for ref in ("R1", "R2"):
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit, ref=ref)
        entry.parts[ref] = p
    return entry


class TestValidate:
    def test_valid_patch_has_no_errors(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]})
        assert validate_patch(entry, patch) == []

    def test_bad_pin_token_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R1.99"]}]})
        errors = validate_patch(entry, patch)
        assert errors and "R1.99" in errors[0]

    def test_unknown_part_ref_in_net_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R7.1"]}]})
        errors = validate_patch(entry, patch)
        assert errors and "R7" in errors[0]

    def test_net_may_reference_pin_on_part_created_by_same_patch(self):
        entry = _two_resistors()
        # U1 is being created in this patch; its pins can't be checked offline, so
        # the token is accepted at validation time (checked at apply).
        patch = DesignPatch.from_obj({
            "parts": [{"ref": "U1", "lib": "Device", "name": "R"}],
            "nets": [{"name": "N", "pins": ["U1.1"]}],
        })
        assert validate_patch(entry, patch) == []

    def test_new_part_without_lib_or_name_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"parts": [{"ref": "U1", "lib": "Device"}]})
        errors = validate_patch(entry, patch)
        assert errors and "U1" in errors[0]

    def test_remove_missing_part_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"remove_parts": ["R9"]})
        errors = validate_patch(entry, patch)
        assert errors and "R9" in errors[0]

    def test_disconnect_unknown_ref_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"disconnect": ["R9.1"]})
        errors = validate_patch(entry, patch)
        assert errors and "R9" in errors[0]

    def test_interface_referencing_unknown_net_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj(
            {"interfaces": [{"name": "i2c0", "nets": {"sda": "NOPE"}}]})
        errors = validate_patch(entry, patch)
        assert errors and "NOPE" in errors[0]
