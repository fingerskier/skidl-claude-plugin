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
