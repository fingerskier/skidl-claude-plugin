"""Integration tests using real KiCad symbol libraries when available."""

from pathlib import Path

import pytest
import skidl
from skidl import KICAD, lib_search_paths

from skidl_mcp import resources
from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, generate, nets, parts, validate

pytestmark = pytest.mark.integration_kicad


def _available_symbol_paths() -> list[Path]:
    """Return discovered KiCad symbol dirs that contain the Device library."""
    paths = []
    for raw_path in resources._find_kicad_lib_paths():
        path = Path(raw_path)
        if (path / "Device.kicad_sym").is_file() or (path / "Device.lib").is_file():
            paths.append(path)
    return paths


@pytest.fixture(autouse=True)
def real_kicad_symbols_or_skip(tmp_path):
    """Configure SKiDL search paths or skip if this machine has no symbols."""
    symbol_paths = _available_symbol_paths()
    if not symbol_paths:
        pytest.skip("KiCad symbol libraries not found")

    original_paths = list(lib_search_paths.get(KICAD, []))
    original_pickle_dir = skidl.config.pickle_dir
    original_search_db_dir = skidl.config.part_search_db_dir
    skidl.config.pickle_dir = str(tmp_path / "lib_pickle_dir")
    skidl.config.part_search_db_dir = str(tmp_path / "part_search_db")
    Path(skidl.config.pickle_dir).mkdir()
    Path(skidl.config.part_search_db_dir).mkdir()

    resources.configure_kicad_library_paths()
    manager.reset()
    yield
    manager.reset()
    lib_search_paths[KICAD] = original_paths
    skidl.config.pickle_dir = original_pickle_dir
    skidl.config.part_search_db_dir = original_search_db_dir


def test_add_part_adds_real_part_to_circuit_and_netlist():
    circuit.create_circuit("real_part")

    add_result = parts.add_part("Device", "R", value="10k", footprint="Resistor_SMD:R_0805_2012Metric")
    assert add_result["status"] == "added"
    assert add_result["ref"]

    entry = manager.get_active()
    assert len(entry.circuit.parts) == 1
    assert add_result["ref"] in entry.parts

    netlist = generate.generate_netlist()
    assert netlist["status"] == "ok"
    comp_count = sum(1 for line in netlist["content"].splitlines() if line.strip() == "(comp")
    assert comp_count == netlist["parts_count"] == 1


def test_run_erc_flags_floating_real_part():
    circuit.create_circuit("bad_erc")
    add_result = parts.add_part("Device", "R", value="10k")
    assert add_result["status"] == "added"

    nets.create_net("VIN")
    connect_result = nets.connect("VIN", add_result["ref"], "1")
    assert connect_result["status"] == "connected"

    erc = validate.run_erc()
    assert erc["status"] == "ok"
    assert erc["passed"] is False
    assert erc["warning_count"] + erc["error_count"] > 0
    assert erc["raw_output"]


def test_connect_real_duplicate_named_power_pins():
    circuit.create_circuit("multi_power")
    add_result = parts.add_part("MCU_Microchip_ATmega", "ATmega328P-A", ref="U1")
    if add_result["status"] == "error":
        pytest.skip(add_result["message"])

    entry = manager.get_active()
    gnd_pins = [pin for pin in entry.parts["U1"].pins if pin.name == "GND"]
    if len(gnd_pins) < 2:
        pytest.skip("ATmega328P-A symbol does not expose duplicate GND pins")

    nets.create_net("GND")
    connect_result = nets.connect("GND", "U1", "GND")
    assert connect_result["status"] == "connected"
    assert connect_result["connected_count"] == len(gnd_pins)

    gnd_net = manager.get_active().nets["GND"]
    connected_gnd = [pin for pin in gnd_net.pins if pin.part.ref == "U1" and pin.name == "GND"]
    assert len(connected_gnd) == len(gnd_pins)
