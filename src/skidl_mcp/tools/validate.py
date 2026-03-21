"""MCP tools for circuit validation and electrical rules checking."""

from __future__ import annotations

import io
import sys

from skidl_mcp.circuit_manager import manager


def run_erc() -> dict:
    """Run Electrical Rules Check (ERC) on the active circuit.

    Checks for common electrical issues like:
    - Unconnected pins that should be connected
    - Multiple outputs driving the same net
    - Missing power connections
    - Pin type conflicts

    Returns:
        ERC results with warnings and errors.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts. Add parts before running ERC."}

        # Capture ERC output (SKiDL prints to stderr)
        old_stderr = sys.stderr
        old_stdout = sys.stdout
        sys.stderr = captured_err = io.StringIO()
        sys.stdout = captured_out = io.StringIO()

        try:
            erc_result = entry.circuit.ERC()
        finally:
            sys.stderr = old_stderr
            sys.stdout = old_stdout

        erc_output = captured_err.getvalue() + captured_out.getvalue()

        # Parse warnings and errors
        warnings = []
        errors = []
        for line in erc_output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if "WARNING" in line.upper() or "warning" in line.lower():
                warnings.append(line)
            elif "ERROR" in line.upper() or "error" in line.lower():
                errors.append(line)
            elif line:
                warnings.append(line)

        passed = len(errors) == 0

        return {
            "status": "ok",
            "passed": passed,
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "raw_output": erc_output.strip(),
            "message": "ERC passed." if passed else f"ERC failed with {len(errors)} error(s) and {len(warnings)} warning(s).",
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}


def check_connections() -> dict:
    """Check for unconnected pins in the active circuit.

    Identifies pins that are not connected to any net, which may indicate
    incomplete wiring. Some unconnected pins may be intentional (e.g. NC pins).

    Returns:
        List of unconnected pins grouped by part.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts."}

        unconnected_by_part = {}
        total_pins = 0
        connected_pins = 0

        for ref, part in entry.parts.items():
            unconnected = []
            for pin in part.pins:
                total_pins += 1
                if not pin.is_connected():
                    unconnected.append({
                        "number": str(pin.num),
                        "name": pin.name,
                    })
                else:
                    connected_pins += 1

            if unconnected:
                unconnected_by_part[ref] = {
                    "part_name": part.name,
                    "unconnected_pins": unconnected,
                    "unconnected_count": len(unconnected),
                }

        return {
            "status": "ok",
            "total_pins": total_pins,
            "connected_pins": connected_pins,
            "unconnected_pins": total_pins - connected_pins,
            "parts_with_unconnected": unconnected_by_part,
            "fully_connected": len(unconnected_by_part) == 0,
            "message": (
                "All pins are connected."
                if len(unconnected_by_part) == 0
                else f"{total_pins - connected_pins} unconnected pin(s) across {len(unconnected_by_part)} part(s)."
            ),
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}


def validate_footprints() -> dict:
    """Check that all parts in the active circuit have valid footprints assigned.

    Parts without footprints cannot be used for PCB layout.

    Returns:
        Validation results showing which parts have/lack footprints.
    """
    try:
        entry = manager.get_active()

        if not entry.parts:
            return {"status": "error", "message": "Circuit has no parts."}

        with_footprint = []
        without_footprint = []

        for ref, part in entry.parts.items():
            fp = str(part.footprint) if part.footprint else ""
            if fp and fp != "None" and fp.strip():
                with_footprint.append({"ref": ref, "name": part.name, "footprint": fp})
            else:
                without_footprint.append({"ref": ref, "name": part.name})

        all_valid = len(without_footprint) == 0

        return {
            "status": "ok",
            "all_valid": all_valid,
            "with_footprint": with_footprint,
            "without_footprint": without_footprint,
            "valid_count": len(with_footprint),
            "missing_count": len(without_footprint),
            "message": (
                "All parts have footprints assigned."
                if all_valid
                else f"{len(without_footprint)} part(s) missing footprints: {[p['ref'] for p in without_footprint]}"
            ),
        }
    except (RuntimeError, Exception) as e:
        return {"status": "error", "message": str(e)}
