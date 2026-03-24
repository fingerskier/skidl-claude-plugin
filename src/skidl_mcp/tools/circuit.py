"""MCP tools for circuit lifecycle management."""

from __future__ import annotations

from skidl_mcp.circuit_manager import manager


def create_circuit(name: str, description: str = "") -> dict:
    """Create a new electronic circuit and set it as the active design.

    Args:
        name: Unique name for the circuit (e.g. "power_supply", "led_driver").
        description: Human-readable description of the circuit's purpose.

    Returns:
        Confirmation with circuit metadata.
    """
    if not name or not name.strip():
        return {"status": "error", "message": "Circuit name cannot be empty."}

    try:
        entry = manager.create(name, description)
        return {
            "status": "created",
            "name": entry.name,
            "description": entry.description,
            "created_at": entry.created_at,
            "message": f"Circuit '{name}' created and set as active.",
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}


def list_circuits() -> dict:
    """List all circuits in the current session with their metadata.

    Returns:
        List of all circuits with name, description, part/net counts, and active status.
    """
    circuits = manager.list_all()
    return {
        "circuits": circuits,
        "count": len(circuits),
        "active": manager.active_name,
    }


def switch_circuit(name: str) -> dict:
    """Switch the active circuit to a different existing circuit.

    Args:
        name: Name of the circuit to switch to.

    Returns:
        Confirmation of the switch.
    """
    try:
        entry = manager.switch(name)
        return {
            "status": "switched",
            "active": name,
            "parts_count": len(entry.parts),
            "nets_count": len(entry.nets),
            "message": f"Active circuit switched to '{name}'.",
        }
    except KeyError as e:
        return {"status": "error", "message": str(e)}


def delete_circuit(name: str) -> dict:
    """Delete a circuit and all its components.

    Args:
        name: Name of the circuit to delete.

    Returns:
        Confirmation of deletion and new active circuit.
    """
    try:
        manager.delete(name)
        return {
            "status": "deleted",
            "name": name,
            "new_active": manager.active_name,
            "message": f"Circuit '{name}' deleted.",
        }
    except KeyError as e:
        return {"status": "error", "message": str(e)}


def get_circuit_info(name: str | None = None) -> dict:
    """Get detailed information about a circuit including all parts, nets, and buses.

    Args:
        name: Circuit name. If None, uses the active circuit.

    Returns:
        Full circuit summary with parts, nets, buses, and metadata.
    """
    try:
        if name:
            entry = manager.get(name)
        else:
            entry = manager.get_active()
        return {"status": "ok", **entry.summary()}
    except (KeyError, RuntimeError) as e:
        return {"status": "error", "message": str(e)}
