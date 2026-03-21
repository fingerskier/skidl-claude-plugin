"""MCP resources for circuit state and KiCad library information."""

from __future__ import annotations

import json
import os
from pathlib import Path

from skidl_mcp.circuit_manager import manager


def get_active_circuit() -> str:
    """Get the current active circuit state as JSON."""
    try:
        entry = manager.get_active()
        return json.dumps(entry.summary(), indent=2)
    except RuntimeError:
        return json.dumps({"error": "No active circuit"})


def get_circuit_by_name(name: str) -> str:
    """Get a specific circuit's state as JSON."""
    try:
        entry = manager.get(name)
        return json.dumps(entry.summary(), indent=2)
    except KeyError:
        return json.dumps({"error": f"Circuit '{name}' not found"})


def list_kicad_libraries() -> str:
    """List available KiCad symbol libraries.

    Searches standard KiCad library paths for .kicad_sym and .lib files.
    """
    lib_paths = _find_kicad_lib_paths()

    libraries = []
    for lib_dir in lib_paths:
        if not os.path.isdir(lib_dir):
            continue
        for entry in sorted(os.listdir(lib_dir)):
            if entry.endswith((".kicad_sym", ".lib")):
                lib_name = entry.rsplit(".", 1)[0]
                full_path = os.path.join(lib_dir, entry)
                libraries.append({
                    "name": lib_name,
                    "path": full_path,
                    "format": "kicad_sym" if entry.endswith(".kicad_sym") else "legacy",
                })

    return json.dumps({
        "search_paths": lib_paths,
        "libraries": libraries,
        "count": len(libraries),
    }, indent=2)


def get_library_parts(lib_name: str) -> str:
    """Get the parts available in a specific KiCad library."""
    try:
        from skidl import lib_search_paths, KICAD

        lib_paths = _find_kicad_lib_paths()

        # Find the library file
        lib_file = None
        for lib_dir in lib_paths:
            for ext in (".kicad_sym", ".lib"):
                candidate = os.path.join(lib_dir, lib_name + ext)
                if os.path.isfile(candidate):
                    lib_file = candidate
                    break
            if lib_file:
                break

        if not lib_file:
            return json.dumps({"error": f"Library '{lib_name}' not found in search paths"})

        # Parse the library to extract part names
        parts = _parse_library_parts(lib_file)

        return json.dumps({
            "library": lib_name,
            "path": lib_file,
            "parts": parts,
            "count": len(parts),
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def _find_kicad_lib_paths() -> list[str]:
    """Find KiCad library paths from environment and standard locations."""
    paths = []

    # Environment variable
    kicad_sym = os.environ.get("KICAD_SYMBOL_DIR", "")
    if kicad_sym:
        paths.append(kicad_sym)

    kicad_root = os.environ.get("KICAD8_SYMBOL_DIR", "") or os.environ.get("KICAD7_SYMBOL_DIR", "") or os.environ.get("KICAD6_SYMBOL_DIR", "")
    if kicad_root:
        paths.append(kicad_root)

    # Standard locations
    standard_paths = [
        "/usr/share/kicad/symbols",
        "/usr/local/share/kicad/symbols",
        "/usr/share/kicad/library",
        str(Path.home() / ".local" / "share" / "kicad" / "symbols"),
        # macOS
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
        # Windows (common)
        "C:/Program Files/KiCad/share/kicad/symbols",
        "C:/Program Files/KiCad/8.0/share/kicad/symbols",
    ]

    for p in standard_paths:
        if os.path.isdir(p) and p not in paths:
            paths.append(p)

    # SKiDL's own search paths
    try:
        from skidl import lib_search_paths, KICAD
        for p in lib_search_paths.get(KICAD, []):
            if p not in paths:
                paths.append(str(p))
    except Exception:
        pass

    return paths


def _parse_library_parts(lib_file: str) -> list[str]:
    """Extract part names from a KiCad library file."""
    parts = []
    try:
        with open(lib_file, "r", errors="ignore") as f:
            content = f.read()

        if lib_file.endswith(".kicad_sym"):
            # KiCad 6+ s-expression format
            import re
            # Match top-level (symbol "PartName" ...) declarations.
            # Sub-symbols use the pattern "ParentName_N_SubName" where N is
            # a digit — skip those to only list top-level parts.
            for match in re.finditer(r'\(symbol\s+"([^"]+)"', content):
                name = match.group(1)
                if not re.search(r'_\d+_', name):
                    parts.append(name)
        else:
            # Legacy .lib format
            for line in content.split("\n"):
                if line.startswith("DEF "):
                    tokens = line.split()
                    if len(tokens) >= 2:
                        parts.append(tokens[1])
    except Exception:
        pass

    return sorted(set(parts))
