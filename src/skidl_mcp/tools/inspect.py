"""Phase C: inspect_design — a compact, filtered, read-only view of the design.

Unlike get_circuit_info (a full dump), this projects only what you ask for, and
defaults to a counts+names summary so agent context stays small (Phase A ethos).
"""

from __future__ import annotations

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import validate

_VALID_BY = ("all", "part", "net", "role", "interface", "issues")


def inspect_design(by: str = "all", name: str = "", detail: str = "summary") -> dict:
    """Return a filtered view of the active circuit.

    Args:
        by: all | part | net | role | interface | issues.
        name: narrows to a single part/net/role/interface (ignored for all/issues).
        detail: summary (counts + names) | full (pins, connections, fields).
    """
    by = (by or "all").strip().lower()
    detail = (detail or "summary").strip().lower()
    if by not in _VALID_BY:
        return {"status": "error", "message": f"Unknown 'by' filter '{by}'. Use one of {list(_VALID_BY)}."}

    try:
        entry = manager.get_active()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    if by == "all":
        return _view_all(entry, detail)
    if by == "part":
        return _view_parts(entry, name, detail)
    if by == "net":
        return _view_nets(entry, name, detail)
    if by == "role":
        return _view_roles(entry, name)
    if by == "interface":
        return _view_interfaces(entry, name)
    return _view_issues(entry)


def _pin_rows(part) -> list[dict]:
    rows = []
    for pin in part.pins:
        rows.append({
            "number": str(pin.num),
            "name": pin.name,
            "net": pin.net.name if getattr(pin, "net", None) else None,
        })
    return rows


def _part_full(ref: str, part, entry) -> dict:
    return {
        "ref": ref,
        "name": part.name,
        "value": str(getattr(part, "value", "") or ""),
        "footprint": str(getattr(part, "footprint", "") or ""),
        "role": entry.roles.get(f"part:{ref}", ""),
        "pins": _pin_rows(part),
    }


def _net_full(net_name: str, net, entry) -> dict:
    conns = []
    for pin in net.pins:
        try:
            conns.append(f"{pin.part.ref}.{pin.num}")
        except (AttributeError, TypeError):
            continue
    return {
        "name": net_name,
        "role": entry.roles.get(f"net:{net_name}", ""),
        "connections": conns,
    }


def _view_all(entry, detail: str) -> dict:
    out = {
        "status": "ok",
        "name": entry.name,
        "counts": {
            "parts": len(entry.parts),
            "nets": len(entry.nets),
            "buses": len(entry.buses),
            "roles": len(entry.roles),
            "interfaces": len(entry.interfaces),
        },
        "parts": list(entry.parts.keys()),
        "nets": list(entry.nets.keys()),
        "interfaces": list(entry.interfaces.keys()),
    }
    if detail == "full":
        out["part_details"] = [_part_full(r, p, entry) for r, p in entry.parts.items()]
        out["net_details"] = [_net_full(n, x, entry) for n, x in entry.nets.items()]
        out["roles"] = dict(entry.roles)
    return out


def _view_parts(entry, name: str, detail: str) -> dict:
    if name:
        if name not in entry.parts:
            return {"status": "error", "message": f"Part '{name}' not found. Available: {list(entry.parts.keys())}"}
        return {"status": "ok", "part": _part_full(name, entry.parts[name], entry)}
    if detail == "full":
        return {"status": "ok", "parts": [_part_full(r, p, entry) for r, p in entry.parts.items()]}
    return {"status": "ok", "parts": list(entry.parts.keys())}


def _view_nets(entry, name: str, detail: str) -> dict:
    if name:
        if name not in entry.nets:
            return {"status": "error", "message": f"Net '{name}' not found. Available: {list(entry.nets.keys())}"}
        return {"status": "ok", "net": _net_full(name, entry.nets[name], entry)}
    if detail == "full":
        return {"status": "ok", "nets": [_net_full(n, x, entry) for n, x in entry.nets.items()]}
    return {"status": "ok", "nets": list(entry.nets.keys())}


def _view_roles(entry, name: str) -> dict:
    roles = dict(entry.roles)
    if name:
        roles = {k: v for k, v in roles.items() if k == name or v == name}
    return {"status": "ok", "roles": roles}


def _view_interfaces(entry, name: str) -> dict:
    if name:
        if name not in entry.interfaces:
            return {"status": "error", "message": f"Interface '{name}' not found. Available: {list(entry.interfaces.keys())}"}
        return {"status": "ok", "interface": entry.interfaces[name]}
    return {"status": "ok", "interfaces": dict(entry.interfaces)}


def _view_issues(entry) -> dict:
    conns = validate.check_connections()
    out = {
        "status": "ok",
        "unconnected_pins": conns.get("unconnected_pins", 0),
        "parts_with_unconnected": conns.get("parts_with_unconnected", {}),
        "fully_connected": conns.get("fully_connected", None),
    }
    if entry.parts:
        erc = validate.run_erc()
        out["erc"] = {
            "passed": erc.get("passed"),
            "errors": erc.get("errors", []),
            "warnings": erc.get("warnings", []),
        }
    return out
