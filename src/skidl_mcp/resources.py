"""MCP resources for circuit state and KiCad library information."""

from __future__ import annotations

import json
import os
from pathlib import Path

import skidl_mcp.skidl_quiet  # noqa: F401  (must precede any skidl import)
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

    except (ImportError, FileNotFoundError, IOError, ValueError, KeyError) as e:
        return json.dumps({"error": str(e)})


def _find_kicad_lib_paths() -> list[str]:
    """Find KiCad library paths from environment and standard locations."""
    paths = []

    def add_path(path: str) -> None:
        if path and path not in paths:
            paths.append(path)

    # Environment variable
    for env_var in (
        "KICAD_SYMBOL_DIR",
        "KICAD10_SYMBOL_DIR",
        "KICAD9_SYMBOL_DIR",
        "KICAD8_SYMBOL_DIR",
        "KICAD7_SYMBOL_DIR",
        "KICAD6_SYMBOL_DIR",
    ):
        add_path(os.environ.get(env_var, ""))

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
        "C:/Program Files/KiCad/10.0/share/kicad/symbols",
        "C:/Program Files/KiCad/9.0/share/kicad/symbols",
        "C:/Program Files/KiCad/8.0/share/kicad/symbols",
        "C:/Program Files/KiCad/7.0/share/kicad/symbols",
        "C:/Program Files/KiCad/6.0/share/kicad/symbols",
    ]

    for p in standard_paths:
        if os.path.isdir(p):
            add_path(p)

    # SKiDL's own search paths
    try:
        from skidl import lib_search_paths, KICAD
        for p in lib_search_paths.get(KICAD, []):
            add_path(str(p))
    except (ImportError, AttributeError):
        pass

    return paths


def configure_kicad_library_paths() -> dict:
    """Append discovered KiCad symbol directories to SKiDL's KICAD search path."""
    from skidl import KICAD, lib_search_paths

    configured = lib_search_paths.setdefault(KICAD, [])
    configured_text = [str(p) for p in configured]
    added = []

    for path in _find_kicad_lib_paths():
        if not os.path.isdir(path) or path in configured_text:
            continue
        configured.append(path)
        configured_text.append(path)
        added.append(path)

    return {
        "status": "ok",
        "tool": KICAD,
        "added_paths": added,
        "configured_paths": [str(p) for p in configured],
        "library_count": _count_libraries(configured),
    }


def kicad_diagnostics() -> dict:
    """Report KiCad symbol discovery, configured SKiDL paths, and cache state."""
    config = configure_kicad_library_paths()
    discovered = _find_kicad_lib_paths()
    return {
        "status": "ok",
        "tool": config["tool"],
        "discovered_paths": discovered,
        "configured_paths": config["configured_paths"],
        "added_paths": config["added_paths"],
        "library_count": _count_libraries(config["configured_paths"]),
        "environment": {
            name: os.environ.get(name, "")
            for name in (
                "KICAD_SYMBOL_DIR",
                "KICAD10_SYMBOL_DIR",
                "KICAD9_SYMBOL_DIR",
                "KICAD8_SYMBOL_DIR",
                "KICAD7_SYMBOL_DIR",
                "KICAD6_SYMBOL_DIR",
            )
        },
        "config_files": _existing_skidl_config_files(),
        "cache": _part_search_cache_info(),
    }


def _count_libraries(paths) -> int:
    """Count KiCad symbol libraries in the supplied directories."""
    libraries = set()
    for raw_path in paths:
        path = Path(str(raw_path))
        if not path.is_dir():
            continue
        for entry in path.iterdir():
            if entry.suffix in (".kicad_sym", ".lib"):
                libraries.add(str(entry.resolve()))
    return len(libraries)


def _existing_skidl_config_files() -> list[str]:
    """Return likely SKiDL config files that could affect library paths."""
    candidates = [
        Path.cwd() / ".skidlcfg",
        Path.home() / ".skidlcfg",
        Path.home() / ".skidl" / "config",
        Path("/etc/skidl/.skidlcfg"),
    ]
    return [str(path) for path in candidates if path.is_file()]


def _part_search_cache_info() -> dict:
    """Return best-effort details about SKiDL's part-search cache."""
    try:
        from skidl import KICAD
        from skidl.part_query import part_search_dbs

        db = part_search_dbs.get(KICAD)
        return {
            "loaded": db is not None,
            "type": type(db).__name__ if db is not None else None,
        }
    except Exception as e:
        return {
            "loaded": False,
            "error": str(e),
        }


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
    except (IOError, OSError, UnicodeDecodeError):
        pass

    return sorted(set(parts))
