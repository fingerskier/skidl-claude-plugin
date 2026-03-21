"""Tests for MCP tool functions."""

import pytest

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, nets, generate, validate


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
