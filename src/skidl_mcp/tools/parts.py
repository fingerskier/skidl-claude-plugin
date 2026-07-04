"""MCP tools for managing electronic components (parts) in circuits."""

from __future__ import annotations

import contextlib
import io
import re
import sys

import skidl_mcp.skidl_quiet  # noqa: F401  (must precede any skidl import)
from skidl import KICAD, Part
from skidl import search_parts as _skidl_search_parts

from skidl_mcp.circuit_manager import manager


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
        footprint: KiCad footprint (e.g. "Resistor_SMD:R_0805_2012Metric"). Leave empty for default.
        ref: Reference designator override (e.g. "R1", "C3"). Auto-assigned if empty.

    Returns:
        Part details including assigned reference and pin information.
    """
    try:
        entry = manager.get_active()

        kwargs = {"dest": KICAD}
        if value:
            kwargs["value"] = value
        if footprint:
            kwargs["footprint"] = footprint
        if ref:
            kwargs["ref"] = ref

        try:
            part = Part(library, name, circuit=entry.circuit, **kwargs)
        except Exception as e:
            # SKiDL signals missing libraries/parts (and KiCad symbol-table
            # problems) through a variety of exception types, so catch broadly
            # at this external-library boundary and return a clean error.
            return {
                "status": "error",
                "message": (
                    f"Could not add part '{name}' from library '{library}': {e}. "
                    "Check the library and part names (use search_parts) and that "
                    "KiCad symbol libraries are installed."
                ),
            }

        assigned_ref = part.ref
        entry.parts[assigned_ref] = part

        pins = []
        for pin in part.pins:
            pins.append({
                "number": str(pin.num),
                "name": pin.name,
                "function": str(pin.func) if hasattr(pin, "func") else "",
            })

        return {
            "status": "added",
            "ref": assigned_ref,
            "library": library,
            "name": name,
            "value": value,
            "footprint": str(getattr(part, "footprint", "") or ""),
            "pin_count": len(pins),
            "pins": pins,
            "message": f"Part {assigned_ref} ({name}) added to circuit '{entry.name}'.",
        }
    except (RuntimeError, KeyError, ValueError) as e:
        return {"status": "error", "message": str(e)}


def search_parts(query: str, library: str = "") -> dict:
    """Search KiCad libraries for electronic components matching a query.

    Args:
        query: Search term (e.g. "resistor", "ATmega", "op amp", "LDO").
        library: Optional library name to search within. Searches all libraries if empty.

    Returns:
        List of matching parts with library, name, and description.
    """
    if not query or not query.strip():
        return {"status": "error", "message": "Search query cannot be empty."}

    # Tab-delimited fields let us parse SKiDL's results structurally instead of
    # scraping free-form console text. The field names match SKiDL's search API.
    fmt = "{lib_name}\t{part_name}\t{description}"

    # A single un-openable library (stale search cache, deleted or corrupt
    # .kicad_sym file) makes SKiDL raise mid-search and abort the whole call.
    # We skip such libraries: prune the offender from SKiDL's cache, then retry
    # so the remaining good libraries still produce results. Re-seeing the same
    # bad library means the prune did not help, so we stop and degrade to a
    # well-formed empty result rather than erroring the tool call.
    skipped: list[str] = []
    seen_bad: set[str] = set()
    # Bound the loop so a pathological cache can never spin forever; the
    # repeat-guard below normally terminates it much sooner.
    for _ in range(64):
        buf = io.StringIO()
        try:
            try:
                _skidl_search_parts(query, fmt=fmt, file=buf)
            except TypeError:
                # Older/newer SKiDL without fmt/file kwargs: fall back to stdout.
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    _skidl_search_parts(query)
        except Exception as e:
            bad = _unopenable_lib_path(e)
            if bad is None:
                # Not a library-open failure — a genuine error worth surfacing.
                return {"status": "error", "message": f"Search failed: {e}"}
            if bad in seen_bad:
                # Pruning did not clear it; stop and return what we can.
                break
            seen_bad.add(bad)
            skipped.append(bad)
            _prune_lib_from_cache(bad)
            continue

        # Search completed without raising — parse the buffered results.
        results = []
        for line in buf.getvalue().splitlines():
            line = line.rstrip()
            if not line:
                continue
            fields = line.split("\t", 2)
            if len(fields) >= 2:
                lib_name, part_name = fields[0], fields[1]
                description = fields[2] if len(fields) > 2 else ""
                # Filter on the library field specifically (forgiving substring).
                if library and library.lower() not in lib_name.lower():
                    continue
                results.append({
                    "library": lib_name,
                    "name": part_name,
                    "description": description,
                })
            else:
                # Unstructured fallback line (stdout path or unexpected format).
                if library and library.lower() not in line.lower():
                    continue
                results.append({"library": "", "name": line, "description": ""})

        return _search_result(query, library, results, skipped)

    # Exhausted retries with an unrecoverable un-openable library: degrade to a
    # well-formed empty result so the caller never sees a hard error.
    return _search_result(query, library, [], skipped)


def _search_result(query: str, library: str, results: list, skipped: list) -> dict:
    """Build the standard search_parts response, noting any skipped libraries."""
    out = {
        "status": "ok",
        "query": query,
        "library_filter": library or "all",
        "results": results,
        "count": len(results),
    }
    if skipped:
        out["skipped_libraries"] = sorted(set(skipped))
    return out


def _unopenable_lib_path(exc: Exception) -> str | None:
    """Return the offending library path if exc is a library-open failure.

    SKiDL signals an unreadable library either as a FileNotFoundError or via a
    "Can't open file: <path>" message. Anything else is a genuine error and
    returns None so the caller can surface it.
    """
    if isinstance(exc, FileNotFoundError) and getattr(exc, "filename", None):
        return str(exc.filename)
    msg = str(exc)
    match = re.search(r"[Cc]an'?t open file:\s*(.+)", msg)
    if match:
        return match.group(1).strip().rstrip(".")
    if isinstance(exc, FileNotFoundError):
        return msg.strip() or "<unknown>"
    return None


def _prune_lib_from_cache(lib_path: str) -> None:
    """Best-effort removal of a library from SKiDL's part-search cache.

    Stale cache entries point at libraries that no longer exist; dropping the
    offender lets a retry of the search succeed using the remaining libraries.
    All access to SKiDL internals is guarded so a layout change there can never
    crash the search tool.
    """
    try:
        import skidl
        from skidl.part_query import part_search_dbs

        tool = skidl.get_default_tool()
        db = part_search_dbs.get(tool)
        if db is not None:
            db.rmv_lib(lib_path)
    except Exception:
        pass


def list_parts(circuit_name: str = "") -> dict:
    """List all parts in a circuit.

    Args:
        circuit_name: Circuit name. Uses active circuit if empty.

    Returns:
        List of all parts with reference, name, value, footprint, and pin count.
    """
    try:
        entry = manager.get(circuit_name) if circuit_name else manager.get_active()
        parts = []
        for ref, part in entry.parts.items():
            parts.append({
                "ref": ref,
                "name": part.name,
                "value": str(getattr(part, "value", "") or ""),
                "footprint": str(getattr(part, "footprint", "") or ""),
                "pin_count": len(part.pins),
            })
        return {
            "status": "ok",
            "circuit": entry.name,
            "parts": parts,
            "count": len(parts),
        }
    except (KeyError, RuntimeError) as e:
        return {"status": "error", "message": str(e)}


def remove_part(ref: str) -> dict:
    """Remove a part from the active circuit by reference designator.

    Args:
        ref: Reference designator (e.g. "R1", "U1", "C3").

    Returns:
        Confirmation of removal.
    """
    try:
        entry = manager.get_active()
        if ref not in entry.parts:
            return {"status": "error", "message": f"Part '{ref}' not found. Available: {list(entry.parts.keys())}"}

        part = entry.parts[ref]
        # Disconnect all pins
        for pin in part.pins:
            pin.disconnect()
        # Remove from circuit's part list
        entry.circuit.rmv_parts(part)
        del entry.parts[ref]

        return {
            "status": "removed",
            "ref": ref,
            "message": f"Part {ref} removed from circuit '{entry.name}'.",
        }
    except (RuntimeError, KeyError) as e:
        return {"status": "error", "message": str(e)}


def get_part_info(ref: str) -> dict:
    """Get detailed information about a part including all pins and connections.

    Args:
        ref: Reference designator (e.g. "R1", "U1").

    Returns:
        Full part details with pin names, numbers, functions, and current connections.
    """
    try:
        entry = manager.get_active()
        part = manager.find_part(ref, entry)

        pins = []
        for pin in part.pins:
            net_name = pin.net.name if pin.net else None
            connected_to = []
            if pin.net:
                for other_pin in pin.net.pins:
                    if other_pin is not pin:
                        connected_to.append(f"{other_pin.part.ref}:{other_pin.name}")
            pins.append({
                "number": str(pin.num),
                "name": pin.name,
                "net": net_name,
                "connected_to": connected_to,
            })

        return {
            "status": "ok",
            "ref": ref,
            "name": part.name,
            "value": str(getattr(part, "value", "") or ""),
            "footprint": str(getattr(part, "footprint", "") or ""),
            "description": str(getattr(part, "description", "") or ""),
            "pins": pins,
        }
    except (KeyError, RuntimeError) as e:
        return {"status": "error", "message": str(e)}
