#!/usr/bin/env python3
"""End-to-end example: build a voltage divider and export artifacts to disk.

This demonstrates the Phase A **file-based workflow**: every generator is given
an ``output_path`` so the full artifact is written to ``artifacts/`` and the tool
returns a compact ``{path, bytes, summary}`` response instead of dumping the whole
netlist/BOM back into the caller's context.

It runs **without KiCad**: the resistors are built as bare SKiDL parts, so the
netlist, BOM, and Python exports all work offline. (``add_part`` / ``search_parts``
and ``generate_svg`` are the only features that need a real KiCad install.)

Run it directly::

    python examples/voltage_divider/build_divider.py

and inspect the files it drops in ``examples/voltage_divider/artifacts/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the example runnable straight from a checkout, with no `pip install -e .`:
# put the package's src/ on the path if skidl_mcp isn't already importable.
_SRC = Path(__file__).resolve().parents[2] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, generate, nets

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def build() -> dict:
    """Build a 12V -> 3.3V divider and write netlist, BOM, and Python to disk.

    Returns a dict of ``{artifact_name: tool_response}`` so callers (and the test)
    can assert on the compact responses.
    """
    manager.reset()
    circuit.create_circuit("voltage_divider", "12V -> 3.3V resistive divider")
    entry = manager.get_active()

    # Two resistors as bare SKiDL parts so the example runs without KiCad.
    # R1 = 8.2k (top), R2 = 3.3k (bottom) gives ~3.44V out from 12V. Refs are set
    # explicitly to R1/R2 — bare parts otherwise fall back to the default 'U' prefix.
    values = [("R1", "8.2k"), ("R2", "3.3k")]
    refs = []
    for ref, value in values:
        part = Part(
            name="R",
            tool=SKIDL,
            ref=ref,
            value=value,
            pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
            circuit=entry.circuit,
        )
        part.footprint = "Resistor_SMD:R_0805_2012Metric"
        entry.parts[part.ref] = part
        refs.append(part.ref)

    # VIN -> R1 -> VOUT (tap) -> R2 -> GND
    nets.create_net("VIN")
    nets.connect("VIN", refs[0], "1")
    nets.connect_pins(refs[0], "2", refs[1], "1", net_name="VOUT")
    nets.create_net("GND")
    nets.connect("GND", refs[1], "2")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return {
        "netlist": generate.generate_netlist(
            output_path=str(ARTIFACTS / "voltage_divider.net")),
        "bom": generate.generate_bom(
            output_format="csv", output_path=str(ARTIFACTS / "voltage_divider_bom.csv")),
        "python": generate.export_python(
            output_path=str(ARTIFACTS / "voltage_divider.py")),
    }


def main() -> None:
    results = build()
    for name, resp in results.items():
        if resp.get("status") == "ok":
            print(f"{name:8} -> {resp['path']} ({resp['bytes']} bytes)")
        else:
            print(f"{name:8} -> ERROR: {resp.get('message')}")


if __name__ == "__main__":
    main()
