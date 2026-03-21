"""MCP tools for generating circuit outputs: netlists, schematics, BOMs."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from collections import Counter

from skidl_mcp.circuit_manager import manager


def generate_netlist() -> dict:
    """Generate a KiCad-compatible netlist for the active circuit.

    The netlist can be imported into KiCad's PCBNEW for PCB layout.

    Returns:
        Netlist content as text.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts. Add parts before generating a netlist."}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".net", delete=False) as f:
            tmp_path = f.name

        try:
            entry.circuit.generate_netlist(file_=tmp_path)
            with open(tmp_path, "r") as f:
                netlist_content = f.read()
        finally:
            os.unlink(tmp_path)

        return {
            "status": "ok",
            "format": "kicad_netlist",
            "content": netlist_content,
            "parts_count": len(entry.parts),
            "nets_count": len(entry.nets),
            "message": f"Netlist generated for circuit '{entry.name}' with {len(entry.parts)} parts and {len(entry.nets)} nets.",
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}


def generate_svg() -> dict:
    """Generate an SVG schematic diagram of the active circuit.

    Returns:
        SVG content as a string that can be rendered as an image.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts. Add parts before generating a schematic."}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".svg", delete=False) as f:
            tmp_path = f.name

        try:
            entry.circuit.generate_svg(file_=tmp_path)
            with open(tmp_path, "r") as f:
                svg_content = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return {
            "status": "ok",
            "format": "svg",
            "content": svg_content,
            "message": f"SVG schematic generated for circuit '{entry.name}'.",
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}


def generate_bom(format: str = "json") -> dict:
    """Generate a Bill of Materials (BOM) for the active circuit.

    Args:
        format: Output format - "json" for structured data, "csv" for spreadsheet-compatible.

    Returns:
        BOM listing all unique parts with quantities and details.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts. Add parts before generating a BOM."}

        # Group parts by (library, name, value, footprint)
        groups: dict[tuple, list[str]] = {}
        for ref, part in entry.parts.items():
            key = (
                str(getattr(part, "lib", "")),
                part.name,
                str(part.value) if part.value else "",
                str(part.footprint) if part.footprint else "",
            )
            groups.setdefault(key, []).append(ref)

        bom_items = []
        for (lib, name, value, footprint), refs in groups.items():
            bom_items.append({
                "quantity": len(refs),
                "references": sorted(refs),
                "name": name,
                "value": value,
                "footprint": footprint,
                "library": lib,
            })

        # Sort by reference
        bom_items.sort(key=lambda x: x["references"][0])

        if format == "csv":
            lines = ["Qty,References,Name,Value,Footprint,Library"]
            for item in bom_items:
                refs_str = " ".join(item["references"])
                lines.append(f"{item['quantity']},{refs_str},{item['name']},{item['value']},{item['footprint']},{item['library']}")
            content = "\n".join(lines)
        else:
            content = json.dumps(bom_items, indent=2)

        return {
            "status": "ok",
            "format": format,
            "content": content,
            "unique_parts": len(bom_items),
            "total_parts": len(entry.parts),
            "message": f"BOM generated: {len(bom_items)} unique parts, {len(entry.parts)} total.",
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}


def generate_kicad_schematic() -> dict:
    """Generate a KiCad schematic file (.kicad_sch) for the active circuit.

    The schematic can be opened in KiCad's schematic editor (Eeschema).

    Returns:
        KiCad schematic file content.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts. Add parts before generating a schematic."}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".kicad_sch", delete=False) as f:
            tmp_path = f.name

        try:
            entry.circuit.generate_schematic(file_=tmp_path)
            with open(tmp_path, "r") as f:
                content = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return {
            "status": "ok",
            "format": "kicad_sch",
            "content": content,
            "message": f"KiCad schematic generated for circuit '{entry.name}'.",
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}


def export_python() -> dict:
    """Export the active circuit as standalone SKiDL Python code.

    The generated code can be run independently to recreate the circuit.

    Returns:
        Python source code as a string.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts."}

        lines = [
            "#!/usr/bin/env python3",
            f'"""SKiDL circuit: {entry.name}',
            f"",
            f"{entry.description}",
            f'"""',
            "",
            "from skidl import *",
            "",
            f"# Circuit: {entry.name}",
            "",
            "# --- Parts ---",
        ]

        # Emit part definitions
        for ref, part in entry.parts.items():
            var_name = ref.lower().replace(".", "_")
            args = [repr(str(getattr(part, "lib", "Device"))), repr(part.name)]
            if part.value:
                args.append(f"value={repr(str(part.value))}")
            if part.footprint:
                args.append(f"footprint={repr(str(part.footprint))}")
            args.append(f"ref={repr(ref)}")
            lines.append(f"{var_name} = Part({', '.join(args)})")

        lines.append("")
        lines.append("# --- Nets ---")

        # Emit net definitions
        for name, net in entry.nets.items():
            var_name = name.lower().replace("+", "p").replace("-", "n").replace(".", "_")
            lines.append(f"{var_name} = Net({repr(name)})")

        lines.append("")
        lines.append("# --- Connections ---")

        # Emit connections
        for name, net in entry.nets.items():
            var_name = name.lower().replace("+", "p").replace("-", "n").replace(".", "_")
            for pin in net.pins:
                part_var = pin.part.ref.lower().replace(".", "_")
                lines.append(f"{var_name} += {part_var}[{repr(str(pin.num))}]  # {pin.name}")

        lines.append("")
        lines.append("# --- Generate outputs ---")
        lines.append("generate_netlist()")
        lines.append("")

        code = "\n".join(lines)

        return {
            "status": "ok",
            "format": "python",
            "content": code,
            "message": f"Python SKiDL code exported for circuit '{entry.name}'.",
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}
