"""SKiDL MCP Server - Design electronic circuits with Claude.

Provides MCP tools, resources, and prompts for schematic-as-code design:
building circuits, validating connectivity (ERC), and exporting
netlists/BOMs/SVG/.kicad_sch artifacts for downstream board layout in KiCad,
using the SKiDL Python library.
"""

from __future__ import annotations

from fastmcp import FastMCP

from skidl_mcp.tools import (
    circuit, parts, nets, generate, validate, project_io, design_patch, inspect,
)
from skidl_mcp.resources import (
    configure_kicad_library_paths,
    get_active_circuit,
    get_circuit_by_name,
    kicad_diagnostics as _kicad_diagnostics,
    list_kicad_libraries,
    get_library_parts,
)
from skidl_mcp.prompts import PROMPTS, get_prompt, list_prompts

configure_kicad_library_paths()

mcp = FastMCP(
    "skidl-circuit-designer",
    instructions=(
        "SKiDL Circuit Designer - helps you design electronic circuits programmatically. "
        "Use the circuit management tools to create circuits, add components from KiCad "
        "libraries, wire them together with nets, validate with ERC, and generate "
        "schematics (SVG), netlists (KiCad), and bills of materials. "
        "Start by creating a circuit, then add parts and connect them. "
        "A local KiCad install is required only for adding parts and searching "
        "component libraries; circuit building, validation, and export work without it."
    ),
)

# ── Circuit Management Tools ────────────────────────────────────────────────

@mcp.tool()
def create_circuit(name: str, description: str = "") -> dict:
    """Create a new electronic circuit and set it as the active design.

    Args:
        name: Unique name for the circuit (e.g. "power_supply", "led_driver").
        description: Human-readable description of the circuit's purpose.
    """
    return circuit.create_circuit(name, description)


@mcp.tool()
def list_circuits() -> dict:
    """List all circuits in the current session with their metadata."""
    return circuit.list_circuits()


@mcp.tool()
def switch_circuit(name: str) -> dict:
    """Switch the active circuit to a different existing circuit.

    Args:
        name: Name of the circuit to switch to.
    """
    return circuit.switch_circuit(name)


@mcp.tool()
def delete_circuit(name: str) -> dict:
    """Delete a circuit and all its components.

    Args:
        name: Name of the circuit to delete.
    """
    return circuit.delete_circuit(name)


@mcp.tool()
def get_circuit_info(name: str | None = None) -> dict:
    """Get detailed information about a circuit including all parts, nets, and buses.

    Args:
        name: Circuit name. If None, uses the active circuit.
    """
    return circuit.get_circuit_info(name)


# ── Parts Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
def add_part(
    library: str,
    name: str,
    value: str = "",
    footprint: str = "",
    ref: str = "",
) -> dict:
    """Add an electronic component to the active circuit.

    Args:
        library: KiCad library name (e.g. "Device", "Connector", "MCU_Microchip_ATmega").
        name: Part name within the library (e.g. "R", "C", "LED", "ATmega328P-AU").
        value: Component value (e.g. "10k", "100nF", "Red").
        footprint: KiCad footprint (e.g. "Resistor_SMD:R_0805_2012Metric").
        ref: Reference designator override (e.g. "R1"). Auto-assigned if empty.
    """
    return parts.add_part(library, name, value, footprint, ref)


@mcp.tool()
def search_parts(query: str, library: str = "") -> dict:
    """Search KiCad libraries for electronic components matching a query.

    Args:
        query: Search term (e.g. "resistor", "ATmega", "op amp", "LDO").
        library: Optional library name to search within. Searches all if empty.
    """
    return parts.search_parts(query, library)


@mcp.tool()
def list_parts(circuit_name: str = "") -> dict:
    """List all parts in a circuit.

    Args:
        circuit_name: Circuit name. Uses active circuit if empty.
    """
    return parts.list_parts(circuit_name)


@mcp.tool()
def remove_part(ref: str) -> dict:
    """Remove a part from the active circuit by reference designator.

    Args:
        ref: Reference designator (e.g. "R1", "U1", "C3").
    """
    return parts.remove_part(ref)


@mcp.tool()
def get_part_info(ref: str) -> dict:
    """Get detailed information about a part including all pins and connections.

    Args:
        ref: Reference designator (e.g. "R1", "U1").
    """
    return parts.get_part_info(ref)


# ── Net Tools ───────────────────────────────────────────────────────────────

@mcp.tool()
def create_net(name: str) -> dict:
    """Create a named electrical net (wire) in the active circuit.

    Args:
        name: Net name (e.g. "VCC", "GND", "CLK", "SDA").
    """
    return nets.create_net(name)


@mcp.tool()
def connect(net_name: str, ref: str, pin: str) -> dict:
    """Connect a part's pin to a named net.

    Args:
        net_name: Name of the net to connect to (must already exist).
        ref: Part reference designator (e.g. "R1", "U1").
        pin: Pin identifier - number (e.g. "1") or name (e.g. "VCC", "PA0").
    """
    return nets.connect(net_name, ref, pin)


@mcp.tool()
def connect_pins(ref1: str, pin1: str, ref2: str, pin2: str, net_name: str = "") -> dict:
    """Directly connect two part pins together, optionally naming the net.

    Args:
        ref1: First part reference (e.g. "R1").
        pin1: First pin identifier (number or name).
        ref2: Second part reference (e.g. "R2").
        pin2: Second pin identifier (number or name).
        net_name: Optional name for the connecting net. Auto-generated if empty.
    """
    return nets.connect_pins(ref1, pin1, ref2, pin2, net_name)


@mcp.tool()
def list_nets(circuit_name: str = "") -> dict:
    """List all nets in a circuit with their connections.

    Args:
        circuit_name: Circuit name. Uses active circuit if empty.
    """
    return nets.list_nets(circuit_name)


@mcp.tool()
def create_bus(name: str, width: int) -> dict:
    """Create a bus (group of related nets) in the active circuit.

    Args:
        name: Bus name (e.g. "DATA", "ADDR").
        width: Number of nets in the bus (e.g. 8 for 8-bit data bus).
    """
    return nets.create_bus(name, width)


@mcp.tool()
def add_power_nets() -> dict:
    """Add standard power nets (VCC, GND, +3V3, +5V, +12V) to the active circuit."""
    return nets.add_power_nets()


# ── Generation Tools ────────────────────────────────────────────────────────

@mcp.tool()
def generate_netlist(output_path: str = "") -> dict:
    """Generate a KiCad-compatible netlist for the active circuit.

    The netlist can be imported into KiCad's PCBNEW for board layout.

    Args:
        output_path: Optional file path. When set, the netlist is written to
            disk and the response is compact ({path, summary, warnings}) instead
            of returning the full netlist inline.
    """
    return generate.generate_netlist(output_path or None)


@mcp.tool()
def generate_svg(output_path: str = "") -> dict:
    """Generate an SVG schematic diagram of the active circuit.

    Returns SVG content that can be rendered as an image.

    Args:
        output_path: Optional file path. When set, the SVG is written to disk
            and the response is compact instead of returning the SVG inline.
    """
    return generate.generate_svg(output_path or None)


@mcp.tool()
def generate_bom(output_format: str = "json", output_path: str = "") -> dict:
    """Generate a Bill of Materials (BOM) for the active circuit.

    Args:
        output_format: Output format - "json" for structured data, "csv" for spreadsheet.
        output_path: Optional file path. When set, the BOM is written to disk
            and the response is compact instead of returning the BOM inline.
    """
    return generate.generate_bom(output_format, output_path or None)


@mcp.tool()
def generate_kicad_schematic(output_path: str = "") -> dict:
    """Generate a KiCad schematic file (.kicad_sch) for the active circuit.

    The schematic can be opened in KiCad's Eeschema.

    Args:
        output_path: Optional file path. When set, the schematic is written to
            disk and the response is compact instead of returning it inline.
    """
    return generate.generate_kicad_schematic(output_path or None)


@mcp.tool()
def export_python(output_path: str = "") -> dict:
    """Export the active circuit as SKiDL Python code.

    The generated script recreates the circuit by re-instantiating each part from
    its source library, so re-running it needs those same libraries (a KiCad
    install for parts from KiCad symbol libraries). It is a faithful round-trip of
    the design, not a dependency-free standalone program.

    Args:
        output_path: Optional file path. When set, the code is written to disk
            and the response is compact instead of returning the code inline.
    """
    return generate.export_python(output_path or None)


# ── Project Persistence Tools ───────────────────────────────────────────────

@mcp.tool()
def open_project(path: str) -> dict:
    """Open a project directory as the active design's source of truth.

    A project directory persists a design across sessions. This creates the
    ``artifacts/`` and ``worlds/`` skeleton if needed, remembers the directory so
    a later ``save_circuit()`` needs no path, and — if the directory already holds
    a ``circuit.json`` — loads that design and makes it active. Loading reads only
    ``circuit.json``; it never executes the project's ``circuit.py``.

    Args:
        path: Project directory (created if it does not exist).
    """
    return project_io.open_project(path)


@mcp.tool()
def save_circuit(path: str = "") -> dict:
    """Save the active circuit to a project directory (its source of truth).

    Writes ``circuit.json`` (authoritative, deterministic, git-diffable structure),
    ``design.yaml`` (human metadata: name, description, requirements) and a
    ``circuit.py`` view. Saving the same circuit twice is byte-identical.

    Args:
        path: Project directory. Defaults to the directory from the most recent
            open_project/save_circuit/load_circuit call.
    """
    return project_io.save_circuit(path or None)


@mcp.tool()
def load_circuit(path: str = "") -> dict:
    """Load a circuit from a project directory, making it the active design.

    Structure is read from ``circuit.json`` only — the project's ``circuit.py`` is
    never imported or executed — so loading is safe and works offline without a
    KiCad install. An in-memory circuit of the same name is replaced.

    Args:
        path: Project directory. Defaults to the current project directory.
    """
    return project_io.load_circuit(path or None)


# ── Design Patch Tools (Phase C) ────────────────────────────────────────────

@mcp.tool()
def apply_design_patch(patch: dict | str, dry_run: bool = False) -> dict:
    """Apply a multi-part, multi-net design change in one structured patch.

    Merge semantics: parts/nets listed are created-or-updated and net pins are
    added. Destructive edits are explicit — ``remove_parts``, ``remove_nets``,
    ``disconnect: ["R1.2"]``, or a net's ``pins_mode: "set"`` (drops pins not
    listed). The whole patch is validated first (nothing changes on error) and is
    rolled back if a mutation fails, so it is atomic and safe to retry.

    Args:
        patch: a mapping or a YAML/JSON string with any of: parts, nets,
            interfaces, remove_parts, remove_nets, disconnect. Parts:
            ref/lib/name/value/footprint/role/fields. Nets: name/role/pins
            (``"R1.1"``/``"U1.SDA"``)/pins_mode. Interfaces: name/type/nets map.
        dry_run: validate and report the diff without changing the circuit.
    """
    return design_patch.apply_design_patch(patch, dry_run=dry_run)


@mcp.tool()
def inspect_design(by: str = "all", name: str = "", detail: str = "summary") -> dict:
    """Inspect the active design through a compact, filtered lens.

    Args:
        by: all | part | net | role | interface | issues.
        name: narrow to a single part/net/role/interface (ignored for all/issues).
        detail: summary (counts + names) | full (pins, connections, fields).
    """
    return inspect.inspect_design(by=by, name=name, detail=detail)


# ── Validation Tools ────────────────────────────────────────────────────────

@mcp.tool()
def run_erc() -> dict:
    """Run Electrical Rules Check (ERC) on the active circuit.

    Checks for unconnected pins, drive conflicts, and missing connections.
    """
    return validate.run_erc()


@mcp.tool()
def check_connections() -> dict:
    """Check for unconnected pins in the active circuit.

    Identifies pins that aren't connected to any net.
    """
    return validate.check_connections()


@mcp.tool()
def validate_footprints() -> dict:
    """Check that all parts have valid footprints for PCB layout."""
    return validate.validate_footprints()


@mcp.tool()
def kicad_diagnostics() -> dict:
    """Report KiCad symbol paths, SKiDL search paths, library count, and cache state."""
    return _kicad_diagnostics()


# ── Resources ───────────────────────────────────────────────────────────────

@mcp.resource("circuit://active")
def resource_active_circuit() -> str:
    """Current active circuit state as JSON."""
    return get_active_circuit()


@mcp.resource("circuit://{name}")
def resource_circuit_by_name(name: str) -> str:
    """Get a specific circuit's state as JSON."""
    return get_circuit_by_name(name)


@mcp.resource("libraries://list")
def resource_library_list() -> str:
    """List of available KiCad symbol libraries."""
    return list_kicad_libraries()


@mcp.resource("libraries://{lib_name}")
def resource_library_parts(lib_name: str) -> str:
    """Parts available in a specific KiCad library."""
    return get_library_parts(lib_name)


# ── Prompts ─────────────────────────────────────────────────────────────────

@mcp.prompt()
def design_voltage_divider(v_in: str, v_out: str, current_ma: str = "") -> str:
    """Design a resistive voltage divider circuit with ratio calculation."""
    return get_prompt("design_voltage_divider", v_in=v_in, v_out=v_out, current_ma=current_ma)


@mcp.prompt()
def design_amplifier(topology: str, gain: str, opamp: str = "") -> str:
    """Design a non-inverting or inverting op-amp amplifier circuit."""
    return get_prompt("design_amplifier", topology=topology, gain=gain, opamp=opamp)


@mcp.prompt()
def design_filter(filter_type: str, cutoff_hz: str, order: str = "1") -> str:
    """Design an active low-pass, high-pass, or band-pass filter."""
    return get_prompt("design_filter", filter_type=filter_type, cutoff_hz=cutoff_hz, order=order)


@mcp.prompt()
def design_oscillator(osc_type: str, frequency_hz: str) -> str:
    """Design a 555 timer or crystal oscillator circuit."""
    return get_prompt("design_oscillator", osc_type=osc_type, frequency_hz=frequency_hz)


@mcp.prompt()
def design_power_supply(regulator_type: str, v_in: str, v_out: str, current_ma: str) -> str:
    """Design a linear or switching voltage regulator circuit."""
    return get_prompt("design_power_supply", regulator_type=regulator_type, v_in=v_in, v_out=v_out, current_ma=current_ma)


@mcp.prompt()
def design_led_circuit(led_color: str, v_supply: str, num_leds: str = "1", current_ma: str = "20") -> str:
    """Design an LED driver circuit with current limiting."""
    return get_prompt("design_led_circuit", led_color=led_color, v_supply=v_supply, num_leds=num_leds, current_ma=current_ma)


@mcp.prompt()
def design_battery_charger(chemistry: str, capacity_mah: str, charge_current_ma: str = "") -> str:
    """Design a Li-ion/LiPo battery charging circuit."""
    return get_prompt("design_battery_charger", chemistry=chemistry, capacity_mah=capacity_mah, charge_current_ma=charge_current_ma)


@mcp.prompt()
def design_microcontroller(mcu: str, clock_mhz: str = "", interfaces: str = "") -> str:
    """Design a microcontroller circuit with essential support components."""
    return get_prompt("design_microcontroller", mcu=mcu, clock_mhz=clock_mhz, interfaces=interfaces)


@mcp.prompt()
def design_logic_level_shifter(v_low: str, v_high: str, channels: str, direction: str = "bidirectional") -> str:
    """Design a voltage level translation circuit."""
    return get_prompt("design_logic_level_shifter", v_low=v_low, v_high=v_high, channels=channels, direction=direction)


@mcp.prompt()
def design_i2c_bus(voltage: str, devices: str, speed: str = "standard") -> str:
    """Design an I2C bus with pull-ups and multiple device connections."""
    return get_prompt("design_i2c_bus", voltage=voltage, devices=devices, speed=speed)


@mcp.prompt()
def design_spi_bus(voltage: str, num_devices: str, devices: str = "") -> str:
    """Design an SPI bus with chip selects for multiple peripherals."""
    return get_prompt("design_spi_bus", voltage=voltage, num_devices=num_devices, devices=devices)


@mcp.prompt()
def design_sensor_interface(sensor_type: str, adc_voltage: str, sensor_range: str = "") -> str:
    """Design an analog sensor input with signal conditioning for ADC."""
    return get_prompt("design_sensor_interface", sensor_type=sensor_type, adc_voltage=adc_voltage, sensor_range=sensor_range)


@mcp.prompt()
def design_motor_driver(motor_type: str, voltage: str, current_a: str) -> str:
    """Design an H-bridge or MOSFET motor driver circuit."""
    return get_prompt("design_motor_driver", motor_type=motor_type, voltage=voltage, current_a=current_a)


@mcp.prompt()
def design_uart_interface(interface_type: str, logic_voltage: str) -> str:
    """Design a UART/RS-232 or UART/USB level converter interface."""
    return get_prompt("design_uart_interface", interface_type=interface_type, logic_voltage=logic_voltage)


@mcp.prompt()
def design_usb_interface(usb_type: str, function: str, voltage: str = "3.3") -> str:
    """Design a USB connector interface with ESD protection."""
    return get_prompt("design_usb_interface", usb_type=usb_type, function=function, voltage=voltage)


@mcp.prompt()
def design_antenna_matching(frequency_mhz: str, z_source: str = "50", topology: str = "pi") -> str:
    """Design an impedance matching network for RF antenna."""
    return get_prompt("design_antenna_matching", frequency_mhz=frequency_mhz, z_source=z_source, topology=topology)


# ── Utility Prompt ──────────────────────────────────────────────────────────

@mcp.prompt()
def list_design_templates() -> str:
    """List all available circuit design templates with descriptions."""
    prompts = list_prompts()
    lines = ["# Available Circuit Design Templates\n"]
    categories = {
        "Analog": ["voltage_divider", "amplifier", "filter", "oscillator"],
        "Power": ["power_supply", "led_circuit", "battery_charger"],
        "Digital": ["microcontroller", "logic_level_shifter", "i2c_bus", "spi_bus"],
        "Interface": ["sensor_interface", "motor_driver", "uart_interface", "usb_interface"],
        "RF": ["antenna_matching"],
    }
    for category, keywords in categories.items():
        lines.append(f"\n## {category}\n")
        for p in prompts:
            if any(kw in p["name"] for kw in keywords):
                args_str = ", ".join(
                    f"{a['name']}{'*' if a.get('required') else ''}"
                    for a in p["arguments"]
                )
                lines.append(f"- **{p['name']}**({args_str}): {p['description']}")
    lines.append("\n\n*Arguments marked with * are required.*")
    return "\n".join(lines)


# ── Entry Point ─────────────────────────────────────────────────────────────

def main():
    """Run the SKiDL MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
