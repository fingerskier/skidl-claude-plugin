"""Tests for MCP tool functions."""

import pytest
from skidl import SKIDL, Net, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, nets, parts, generate, validate


def _make_part(entry, name="R", ref=None, pin_names=("p1", "p2"), footprint=""):
    """Create a simple SKiDL part and register it in the circuit entry."""
    pins = [Pin(num=i + 1, name=n) for i, n in enumerate(pin_names)]
    p = Part(name=name, tool=SKIDL, pins=pins, circuit=entry.circuit)
    if footprint:
        p.footprint = footprint
    assigned_ref = p.ref
    entry.parts[assigned_ref] = p
    return assigned_ref, p


@pytest.fixture(autouse=True)
def clean_manager():
    """Reset the global manager before each test."""
    manager.reset()
    yield
    manager.reset()


class TestCircuitTools:
    def test_create_circuit(self):
        result = circuit.create_circuit("mycirc", "test circuit")
        assert result["status"] == "created"
        assert result["name"] == "mycirc"

    def test_create_duplicate_circuit(self):
        circuit.create_circuit("mycirc")
        result = circuit.create_circuit("mycirc")
        assert result["status"] == "error"

    def test_list_circuits(self):
        circuit.create_circuit("a")
        circuit.create_circuit("b")
        result = circuit.list_circuits()
        assert result["count"] == 2

    def test_get_circuit_info_no_circuit(self):
        result = circuit.get_circuit_info()
        assert result["status"] == "error"

    def test_delete_circuit(self):
        circuit.create_circuit("tmp")
        result = circuit.delete_circuit("tmp")
        assert result["status"] == "deleted"

    def test_switch_circuit(self):
        circuit.create_circuit("a")
        circuit.create_circuit("b")
        result = circuit.switch_circuit("a")
        assert result["status"] == "switched"


class TestNetTools:
    def test_create_net(self):
        circuit.create_circuit("c1")
        result = nets.create_net("VCC")
        assert result["status"] == "created"
        assert result["name"] == "VCC"

    def test_create_duplicate_net(self):
        circuit.create_circuit("c1")
        nets.create_net("VCC")
        result = nets.create_net("VCC")
        assert result["status"] == "error"

    def test_list_nets(self):
        circuit.create_circuit("c1")
        nets.create_net("VCC")
        nets.create_net("GND")
        result = nets.list_nets()
        assert result["count"] == 2

    def test_create_bus(self):
        circuit.create_circuit("c1")
        result = nets.create_bus("DATA", 8)
        assert result["status"] == "created"
        assert result["width"] == 8
        assert len(result["net_names"]) == 8

    def test_add_power_nets(self):
        circuit.create_circuit("c1")
        result = nets.add_power_nets()
        assert result["status"] == "ok"
        assert len(result["created"]) == 5

    def test_add_power_nets_idempotent(self):
        circuit.create_circuit("c1")
        nets.add_power_nets()
        result = nets.add_power_nets()
        assert result["status"] == "ok"
        assert len(result["created"]) == 0
        assert len(result["skipped"]) == 5


class TestGenerateTools:
    def test_generate_netlist_no_parts(self):
        circuit.create_circuit("c1")
        result = generate.generate_netlist()
        assert result["status"] == "error"

    def test_generate_svg_no_parts(self):
        circuit.create_circuit("c1")
        result = generate.generate_svg()
        assert result["status"] == "error"

    def test_generate_bom_no_parts(self):
        circuit.create_circuit("c1")
        result = generate.generate_bom()
        assert result["status"] == "error"

    def test_export_python_no_parts(self):
        circuit.create_circuit("c1")
        result = generate.export_python()
        assert result["status"] == "error"


class TestValidateTools:
    def test_run_erc_no_parts(self):
        circuit.create_circuit("c1")
        result = validate.run_erc()
        assert result["status"] == "error"

    def test_check_connections_no_parts(self):
        circuit.create_circuit("c1")
        result = validate.check_connections()
        assert result["status"] == "error"

    def test_validate_footprints_no_parts(self):
        circuit.create_circuit("c1")
        result = validate.validate_footprints()
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Integration tests with real SKiDL Part objects (no KiCad required)
# ---------------------------------------------------------------------------


class TestPartTools:
    def test_list_parts_empty(self):
        circuit.create_circuit("c1")
        result = parts.list_parts()
        assert result["status"] == "ok"
        assert result["count"] == 0

    def test_list_parts_with_parts(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        _make_part(entry, name="R")
        _make_part(entry, name="C")
        result = parts.list_parts()
        assert result["status"] == "ok"
        assert result["count"] == 2

    def test_get_part_info(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R", pin_names=("p1", "p2"))
        result = parts.get_part_info(ref)
        assert result["status"] == "ok"
        assert result["ref"] == ref
        assert result["name"] == "R"
        assert len(result["pins"]) == 2

    def test_get_part_info_not_found(self):
        circuit.create_circuit("c1")
        result = parts.get_part_info("R99")
        assert result["status"] == "error"

    def test_remove_part(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R")
        result = parts.remove_part(ref)
        assert result["status"] == "removed"
        assert parts.list_parts()["count"] == 0

    def test_remove_part_not_found(self):
        circuit.create_circuit("c1")
        result = parts.remove_part("X99")
        assert result["status"] == "error"


class TestNetToolsWithParts:
    def test_connect_pin_to_net(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R", pin_names=("p1", "p2"))
        nets.create_net("VCC")
        result = nets.connect("VCC", ref, "1")
        assert result["status"] == "connected"
        assert result["total_connections"] == 1

    def test_connect_invalid_pin(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R", pin_names=("p1", "p2"))
        nets.create_net("VCC")
        result = nets.connect("VCC", ref, "99")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_connect_pins_directly(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref1, _ = _make_part(entry, name="R")
        ref2, _ = _make_part(entry, name="C")
        result = nets.connect_pins(ref1, "1", ref2, "1")
        assert result["status"] == "connected"
        assert result["net"]  # auto-generated name

    def test_connect_pins_with_named_net(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref1, _ = _make_part(entry, name="R")
        ref2, _ = _make_part(entry, name="C")
        result = nets.connect_pins(ref1, "1", ref2, "1", net_name="SIG")
        assert result["status"] == "connected"
        assert result["net"] == "SIG"


class TestGenerateToolsWithParts:
    def test_generate_bom_json(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        _make_part(entry, name="R")
        _make_part(entry, name="R")
        _make_part(entry, name="C")
        result = generate.generate_bom(output_format="json")
        assert result["status"] == "ok"
        assert result["total_parts"] == 3
        assert result["unique_parts"] == 2  # R and C

    def test_generate_bom_csv(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        _make_part(entry, name="R")
        result = generate.generate_bom(output_format="csv")
        assert result["status"] == "ok"
        assert "Qty" in result["content"]
        assert "References" in result["content"]

    def test_export_python(self):
        circuit.create_circuit("c1", "test export")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R")
        nets.create_net("VCC")
        nets.connect("VCC", ref, "1")
        result = generate.export_python()
        assert result["status"] == "ok"
        assert "from skidl import" in result["content"]
        assert "Part(" in result["content"]
        assert "Net(" in result["content"]


class TestValidateToolsWithParts:
    def test_check_connections_all_unconnected(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        _make_part(entry, name="R", pin_names=("p1", "p2"))
        result = validate.check_connections()
        assert result["status"] == "ok"
        assert result["fully_connected"] is False
        assert result["unconnected_pins"] == 2

    def test_check_connections_partial(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R", pin_names=("p1", "p2"))
        nets.create_net("VCC")
        nets.connect("VCC", ref, "1")
        result = validate.check_connections()
        assert result["status"] == "ok"
        assert result["connected_pins"] == 1
        assert result["unconnected_pins"] == 1

    def test_validate_footprints_missing(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        _make_part(entry, name="R")
        result = validate.validate_footprints()
        assert result["status"] == "ok"
        assert result["all_valid"] is False
        assert result["missing_count"] == 1

    def test_validate_footprints_present(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        _make_part(entry, name="R", footprint="Resistor_SMD:R_0805")
        result = validate.validate_footprints()
        assert result["status"] == "ok"
        assert result["all_valid"] is True
        assert result["valid_count"] == 1


class TestCircuitEntrySummary:
    """Verify CircuitEntry.summary() handles SKIDL-tool parts without AttributeError."""

    def test_summary_with_skidl_parts(self):
        circuit.create_circuit("c1", "summary test")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R", pin_names=("p1", "p2"))
        result = entry.summary()
        assert result["name"] == "c1"
        assert result["parts_count"] == 1
        # value/footprint should be None for bare SKIDL parts
        part_info = result["parts"][0]
        assert part_info["ref"] == ref
        assert part_info["pin_count"] == 2

    def test_summary_with_nets_and_connections(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        ref, _ = _make_part(entry, name="R", pin_names=("p1", "p2"))
        nets.create_net("VCC")
        nets.connect("VCC", ref, "1")
        result = entry.summary()
        assert result["nets_count"] == 1
        assert len(result["nets"][0]["connections"]) == 1


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Verify that invalid inputs are rejected with clear error messages."""

    def test_create_circuit_empty_name(self):
        result = circuit.create_circuit("")
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

    def test_create_circuit_whitespace_name(self):
        result = circuit.create_circuit("   ")
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

    def test_create_net_empty_name(self):
        circuit.create_circuit("c1")
        result = nets.create_net("")
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

    def test_create_net_whitespace_name(self):
        circuit.create_circuit("c1")
        result = nets.create_net("  ")
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

    def test_create_bus_empty_name(self):
        circuit.create_circuit("c1")
        result = nets.create_bus("", 8)
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

    def test_create_bus_zero_width(self):
        circuit.create_circuit("c1")
        result = nets.create_bus("DATA", 0)
        assert result["status"] == "error"
        assert "positive" in result["message"].lower()

    def test_create_bus_negative_width(self):
        circuit.create_circuit("c1")
        result = nets.create_bus("DATA", -1)
        assert result["status"] == "error"
        assert "positive" in result["message"].lower()

    def test_generate_bom_invalid_format(self):
        circuit.create_circuit("c1")
        entry = manager.get_active()
        _make_part(entry, name="R")
        result = generate.generate_bom(output_format="xml")
        assert result["status"] == "error"
        assert "invalid format" in result["message"].lower()
