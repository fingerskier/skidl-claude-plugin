"""MCP tools for generating circuit outputs: netlists, schematics, BOMs."""

from __future__ import annotations

import csv
import io
import json
import keyword
import os
import re
import tempfile

from skidl_mcp.circuit_manager import manager


def _to_python_var(name: str, seen: set[str]) -> str:
    """Convert a part ref or net name to a unique, valid Python identifier."""
    var = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().replace("+", "p").replace("-", "n"))
    if not var or var[0].isdigit():
        var = f"_{var}"
    if keyword.iskeyword(var):
        var = f"{var}_"
    # Ensure uniqueness
    base = var
    counter = 2
    while var in seen:
        var = f"{base}_{counter}"
        counter += 1
    seen.add(var)
    return var


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
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return {
            "status": "ok",
            "format": "kicad_netlist",
            "content": netlist_content,
            "parts_count": len(entry.parts),
            "nets_count": len(entry.nets),
            "message": f"Netlist generated for circuit '{entry.name}' with {len(entry.parts)} parts and {len(entry.nets)} nets.",
        }
    except (RuntimeError, FileNotFoundError, OSError) as e:
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
    except (RuntimeError, FileNotFoundError, OSError) as e:
        return {"status": "error", "message": str(e)}


def generate_bom(output_format: str = "json") -> dict:
    """Generate a Bill of Materials (BOM) for the active circuit.

    Args:
        output_format: Output format - "json" for structured data, "csv" for spreadsheet-compatible.

    Returns:
        BOM listing all unique parts with quantities and details.
    """
    valid_formats = ("json", "csv")
    if output_format not in valid_formats:
        return {"status": "error", "message": f"Invalid format '{output_format}'. Must be one of: {', '.join(valid_formats)}."}

    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts. Add parts before generating a BOM."}

        # Group parts by (library, name, value, footprint)
        groups: dict[tuple, list[str]] = {}
        for ref, part in entry.parts.items():
            key = (
                str(getattr(part, "lib", "") or ""),
                part.name,
                str(getattr(part, "value", "") or ""),
                str(getattr(part, "footprint", "") or ""),
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

        if output_format == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["Qty", "References", "Name", "Value", "Footprint", "Library"])
            for item in bom_items:
                writer.writerow([
                    item["quantity"],
                    " ".join(item["references"]),
                    item["name"],
                    item["value"],
                    item["footprint"],
                    item["library"],
                ])
            content = buf.getvalue()
        else:
            content = json.dumps(bom_items, indent=2)

        return {
            "status": "ok",
            "format": output_format,
            "content": content,
            "unique_parts": len(bom_items),
            "total_parts": len(entry.parts),
            "message": f"BOM generated: {len(bom_items)} unique parts, {len(entry.parts)} total.",
        }
    except (RuntimeError, KeyError) as e:
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
    except (RuntimeError, FileNotFoundError, OSError) as e:
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

        # Build unique variable name mappings
        seen_vars: set[str] = set()
        part_vars: dict[str, str] = {}  # ref -> var_name
        net_vars: dict[str, str] = {}   # net name -> var_name

        # Emit part definitions
        for ref, part in entry.parts.items():
            var_name = _to_python_var(ref, seen_vars)
            part_vars[ref] = var_name
            lib = str(getattr(part, "lib", "Device") or "Device")
            value = str(getattr(part, "value", "") or "")
            footprint = str(getattr(part, "footprint", "") or "")
            args = [repr(lib), repr(part.name)]
            if value:
                args.append(f"value={repr(value)}")
            if footprint:
                args.append(f"footprint={repr(footprint)}")
            args.append(f"ref={repr(ref)}")
            lines.append(f"{var_name} = Part({', '.join(args)})")

        lines.append("")
        lines.append("# --- Nets ---")

        # Emit net definitions
        for name, net in entry.nets.items():
            var_name = _to_python_var(name, seen_vars)
            net_vars[name] = var_name
            lines.append(f"{var_name} = Net({repr(name)})")

        lines.append("")
        lines.append("# --- Connections ---")

        # Emit connections
        for name, net in entry.nets.items():
            nvar = net_vars[name]
            for pin in net.pins:
                pvar = part_vars.get(pin.part.ref, pin.part.ref.lower())
                lines.append(f"{nvar} += {pvar}[{repr(str(pin.num))}]  # {pin.name}")

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
    except (RuntimeError, KeyError) as e:
        return {"status": "error", "message": str(e)}
