"""Phase C tests: inspect_design filtered read-only view."""

import pytest
from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit
from skidl_mcp.tools.design_patch import apply_design_patch
from skidl_mcp.tools.inspect import inspect_design


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


def _demo():
    circuit.create_circuit("demo")
    entry = manager.get_active()
    for ref in ("R1", "R2"):
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit, ref=ref)
        entry.parts[ref] = p
    apply_design_patch({
        "parts": [{"ref": "R1", "role": "pullup"}],
        "nets": [{"name": "SDA", "role": "i2c_data", "pins": ["R1.1", "R2.1"]}],
        "interfaces": [{"name": "i2c0", "type": "i2c", "nets": {"sda": "SDA"}}],
    })
    return entry


class TestInspectDesign:
    def test_all_summary_has_counts_and_names(self):
        _demo()
        res = inspect_design(by="all", detail="summary")
        assert res["status"] == "ok"
        assert res["counts"] == {"parts": 2, "nets": 1, "buses": 0,
                                 "roles": 2, "interfaces": 1}
        assert set(res["parts"]) == {"R1", "R2"}
        assert res["nets"] == ["SDA"]

    def test_part_filter_by_name_full(self):
        _demo()
        res = inspect_design(by="part", name="R1", detail="full")
        assert res["status"] == "ok"
        assert res["part"]["ref"] == "R1"
        assert res["part"]["role"] == "pullup"
        assert any(p["number"] == "1" for p in res["part"]["pins"])

    def test_net_filter_lists_connections(self):
        _demo()
        res = inspect_design(by="net", name="SDA", detail="full")
        assert res["status"] == "ok"
        assert res["net"]["name"] == "SDA"
        assert res["net"]["role"] == "i2c_data"
        assert sorted(res["net"]["connections"]) == ["R1.1", "R2.1"]

    def test_role_filter(self):
        _demo()
        res = inspect_design(by="role")
        assert res["status"] == "ok"
        assert res["roles"]["part:R1"] == "pullup"
        assert res["roles"]["net:SDA"] == "i2c_data"

    def test_interface_filter(self):
        _demo()
        res = inspect_design(by="interface", name="i2c0")
        assert res["status"] == "ok"
        assert res["interface"]["nets"] == {"sda": "SDA"}

    def test_issues_surfaces_unconnected_pin(self):
        _demo()  # R1.2 and R2.2 are unconnected
        res = inspect_design(by="issues")
        assert res["status"] == "ok"
        assert res["unconnected_pins"] >= 2
        assert "R1" in res["parts_with_unconnected"]

    def test_unknown_by_reports_error(self):
        _demo()
        res = inspect_design(by="bogus")
        assert res["status"] == "error"

    def test_no_active_circuit_reports_error(self):
        res = inspect_design(by="all")
        assert res["status"] == "error"
