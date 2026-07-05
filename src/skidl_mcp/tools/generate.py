"""MCP tools for generating circuit outputs: netlists, schematics, BOMs."""

from __future__ import annotations

import csv
import io
import json
import keyword
import os
import re
import shutil
import tempfile

from skidl_mcp.circuit_manager import manager, part_library_name


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
            # do_backup=False: the default writes a <script>_lib_sklib.py
            # backup library into the server's CWD — the user's project.
            entry.circuit.generate_netlist(file_=tmp_path, do_backup=False)
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
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    if not entry.parts:
        return {"status": "error", "message": "Circuit has no parts. Add parts before generating a schematic."}

    # SKiDL's generate_svg treats file_ as a *basename* and appends ".svg"
    # (also writing .json/_skin.svg intermediates), so pass a directory-scoped
    # basename without extension and read back basename + ".svg".
    tmp_dir = tempfile.mkdtemp(prefix="skidl_svg_")
    basename = os.path.join(tmp_dir, "schematic")
    try:
        entry.circuit.generate_svg(file_=basename)
        svg_path = basename + ".svg"
        if not os.path.exists(svg_path):
            return {
                "status": "error",
                "message": "SVG generation produced no output file. This feature "
                           "requires the 'netlistsvg' tool (and graphviz) to be installed.",
            }
        with open(svg_path, "r") as f:
            svg_content = f.read()
    except Exception as e:
        return {
            "status": "error",
            "message": f"SVG generation failed: {e or type(e).__name__}. This feature "
                       "requires the 'netlistsvg' tool and graphviz to be installed.",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "status": "ok",
        "format": "svg",
        "content": svg_content,
        "message": f"SVG schematic generated for circuit '{entry.name}'.",
    }


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
                part_library_name(part, "") or "",
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
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    if not entry.parts:
        return {"status": "error", "message": "Circuit has no parts. Add parts before generating a schematic."}

    # SKiDL's generate_schematic writes into a *directory* (filepath) using
    # top_name as the base filename — it does not accept a single output file.
    tmp_dir = tempfile.mkdtemp(prefix="skidl_sch_")
    top_name = "schematic"
    try:
        entry.circuit.generate_schematic(filepath=tmp_dir, top_name=top_name)
        sch_path = os.path.join(tmp_dir, f"{top_name}.kicad_sch")
        if not os.path.exists(sch_path):
            produced = [f for f in os.listdir(tmp_dir) if f.endswith(".kicad_sch")]
            if not produced:
                return {
                    "status": "error",
                    "message": "Schematic generation produced no .kicad_sch file.",
                }
            sch_path = os.path.join(tmp_dir, produced[0])
        with open(sch_path, "r") as f:
            content = f.read()
    except Exception as e:
        return {
            "status": "error",
            "message": f"Schematic generation failed: {e or type(e).__name__}. SKiDL's "
                       "schematic generator is experimental and requires parts from real "
                       "KiCad symbol libraries (added via add_part), not bare parts.",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "status": "ok",
        "format": "kicad_sch",
        "content": content,
        "message": f"KiCad schematic generated for circuit '{entry.name}'.",
    }


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
            lib = part_library_name(part, "Device") or "Device"
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
