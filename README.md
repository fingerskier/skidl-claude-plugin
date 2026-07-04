# skidl-claude-plugin

MCP server for designing electronic schematics and PCB layouts using [SKiDL](https://github.com/devbisme/skidl) — a Python library for programmatic circuit design.

## Features

- **Circuit Management** — Create, switch between, and manage multiple circuit designs
- **Component Library** — Search and add parts from your local KiCad libraries
- **Wiring** — Create nets, buses, and connect component pins
- **Schematic Generation** — Export SVG schematics and KiCad `.kicad_sch` files
- **Netlist Export** — Generate KiCad-compatible netlists for PCB layout in PCBNEW
- **Validation** — Run electrical rules checks (ERC), verify connections and footprints
- **BOM Generation** — Bill of materials in JSON or CSV format
- **Code Export** — Export circuits as standalone SKiDL Python scripts
- **16 Design Templates** — Prompt templates for common circuits (voltage dividers, amplifiers, filters, MCU designs, motor drivers, USB interfaces, and more)

## Prerequisites

- Python 3.10+
- [KiCad](https://www.kicad.org/) installed — only required for adding parts and searching component libraries. Circuit building, validation, and netlist/BOM/Python export work without it.
- *Optional:* [`netlistsvg`](https://github.com/nturley/netlistsvg) for `generate_svg`. SKiDL's `generate_kicad_schematic` is experimental and needs parts from real KiCad symbol libraries.

## Installation

This repository is both a **Claude Code plugin** and a standalone **MCP server**.

### As a Claude Code plugin

The plugin ships its MCP server definition in [`.mcp.json`](./.mcp.json), which runs the server via [`uvx`](https://docs.astral.sh/uv/) straight from this repo — no manual install step is needed. Just make sure [`uv`](https://docs.astral.sh/uv/getting-started/installation/) is installed so `uvx` is on your PATH.

### Manual install (standalone / Claude Desktop)

```bash
pip install -e .
```

This exposes the `skidl-mcp` console script.

## Usage

### Run the MCP server directly (stdio)

```bash
skidl-mcp
```

### With Claude Code

Register the server with the CLI:

```bash
claude mcp add skidl -- uvx --from git+https://github.com/fingerskier/skidl-claude-plugin skidl-mcp
```

### With Claude Desktop

Add to `~/.claude/claude_desktop_config.json` (requires the manual `pip install` above):

```json
{
  "mcpServers": {
    "skidl": {
      "command": "skidl-mcp"
    }
  }
}
```

Then ask Claude to design circuits:

> "Design a voltage divider that converts 12V to 3.3V"
> "Create an ATmega328P circuit with UART and I2C headers"
> "Build an LED driver for 4 blue LEDs on a 5V supply"

## MCP Tools

### Circuit Management
| Tool | Description |
|------|-------------|
| `create_circuit` | Create a new circuit and set it as active |
| `list_circuits` | List all circuits in the session |
| `switch_circuit` | Switch the active circuit |
| `delete_circuit` | Delete a circuit |
| `get_circuit_info` | Get full details of a circuit |

### Parts
| Tool | Description |
|------|-------------|
| `add_part` | Add a component from a KiCad library |
| `search_parts` | Search KiCad libraries for components |
| `list_parts` | List all parts in a circuit |
| `remove_part` | Remove a part by reference designator |
| `get_part_info` | Get pin details and connections for a part |

### Nets & Wiring
| Tool | Description |
|------|-------------|
| `create_net` | Create a named net |
| `connect` | Connect a pin to a net |
| `connect_pins` | Connect two pins directly |
| `list_nets` | List all nets and connections |
| `create_bus` | Create a multi-wire bus |
| `add_power_nets` | Add standard power nets (VCC, GND, etc.) |

### Generation & Export
| Tool | Description |
|------|-------------|
| `generate_netlist` | KiCad-compatible netlist for PCBNEW |
| `generate_svg` | SVG schematic diagram |
| `generate_bom` | Bill of materials (JSON or CSV) |
| `generate_kicad_schematic` | KiCad `.kicad_sch` file |
| `export_python` | Standalone SKiDL Python code |

### Validation
| Tool | Description |
|------|-------------|
| `run_erc` | Electrical rules check |
| `check_connections` | Find unconnected pins |
| `validate_footprints` | Verify all parts have footprints |

## Design Templates

Use these prompts to guide circuit design:

| Category | Templates |
|----------|-----------|
| **Analog** | `design_voltage_divider`, `design_amplifier`, `design_filter`, `design_oscillator` |
| **Power** | `design_power_supply`, `design_led_circuit`, `design_battery_charger` |
| **Digital** | `design_microcontroller`, `design_logic_level_shifter`, `design_i2c_bus`, `design_spi_bus` |
| **Interface** | `design_sensor_interface`, `design_motor_driver`, `design_uart_interface`, `design_usb_interface` |
| **RF** | `design_antenna_matching` |

## Development

```bash
pip install -e ".[dev]"     # see HOWTO.md §2 if the build trips on kinet2pcb/hierplace
pytest                      # 74 tests; no PYTHONPATH needed
```

[HOWTO.md](./HOWTO.md) covers local setup (including the SKiDL transitive-dependency
build gotcha), the test layout, a manual end-to-end smoke test, and which features
need a real KiCad install to verify. [PLAN.md](./PLAN.md) holds the upgrade roadmap.

## License

MIT
