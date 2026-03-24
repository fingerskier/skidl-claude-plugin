"""MCP tools for managing nets (electrical connections) in circuits."""

from __future__ import annotations

from skidl import Bus, Net

from skidl_mcp.circuit_manager import manager


def create_net(name: str) -> dict:
    """Create a named electrical net (wire) in the active circuit.

    Args:
        name: Net name (e.g. "VCC", "GND", "CLK", "SDA"). Use descriptive names.

    Returns:
        Confirmation with net details.
    """
    if not name or not name.strip():
        return {"status": "error", "message": "Net name cannot be empty."}

    try:
        entry = manager.get_active()
        if name in entry.nets:
            return {"status": "error", "message": f"Net '{name}' already exists in circuit '{entry.name}'."}
        net = Net(name, circuit=entry.circuit)
        entry.nets[name] = net
        return {
            "status": "created",
            "name": name,
            "circuit": entry.name,
            "message": f"Net '{name}' created in circuit '{entry.name}'.",
        }
    except (RuntimeError, KeyError) as e:
        return {"status": "error", "message": str(e)}


def connect(net_name: str, ref: str, pin: str) -> dict:
    """Connect a part's pin to a named net.

    Args:
        net_name: Name of the net to connect to (must already exist).
        ref: Part reference designator (e.g. "R1", "U1").
        pin: Pin identifier - either pin number (e.g. "1", "2") or pin name (e.g. "VCC", "PA0").

    Returns:
        Confirmation of the connection.
    """
    try:
        entry = manager.get_active()
        net = manager.find_net(net_name, entry)
        part = manager.find_part(ref, entry)

        # Try pin by number first, then by name
        target_pin = None
        for p in part.pins:
            if str(p.num) == str(pin) or p.name == pin:
                target_pin = p
                break

        if target_pin is None:
            pin_list = [f"{p.num}({p.name})" for p in part.pins]
            return {
                "status": "error",
                "message": f"Pin '{pin}' not found on {ref}. Available pins: {pin_list}",
            }

        net += target_pin

        return {
            "status": "connected",
            "net": net_name,
            "part": ref,
            "pin": f"{target_pin.num}({target_pin.name})",
            "total_connections": len(net.pins),
            "message": f"Connected {ref} pin {target_pin.num}({target_pin.name}) to net '{net_name}'.",
        }
    except (KeyError, RuntimeError) as e:
        return {"status": "error", "message": str(e)}


def connect_pins(ref1: str, pin1: str, ref2: str, pin2: str, net_name: str = "") -> dict:
    """Directly connect two part pins together, optionally creating a named net.

    Args:
        ref1: First part reference (e.g. "R1").
        pin1: First pin identifier (number or name).
        ref2: Second part reference (e.g. "R2").
        pin2: Second pin identifier (number or name).
        net_name: Optional name for the connecting net. Auto-generated if empty.

    Returns:
        Confirmation with connection details.
    """
    try:
        entry = manager.get_active()
        part1 = manager.find_part(ref1, entry)
        part2 = manager.find_part(ref2, entry)

        # Find pins
        p1 = _find_pin(part1, pin1, ref1)
        p2 = _find_pin(part2, pin2, ref2)
        if isinstance(p1, dict):
            return p1  # Error
        if isinstance(p2, dict):
            return p2  # Error

        # Create or reuse net
        if net_name:
            if net_name in entry.nets:
                net = entry.nets[net_name]
            else:
                net = Net(net_name, circuit=entry.circuit)
                entry.nets[net_name] = net
        else:
            auto_name = f"{ref1}_{pin1}__{ref2}_{pin2}"
            net = Net(auto_name, circuit=entry.circuit)
            entry.nets[auto_name] = net
            net_name = auto_name

        net += p1, p2

        return {
            "status": "connected",
            "net": net_name,
            "pin1": f"{ref1}:{p1.num}({p1.name})",
            "pin2": f"{ref2}:{p2.num}({p2.name})",
            "message": f"Connected {ref1}:{p1.name} to {ref2}:{p2.name} via net '{net_name}'.",
        }
    except (KeyError, RuntimeError) as e:
        return {"status": "error", "message": str(e)}


def list_nets(circuit_name: str = "") -> dict:
    """List all nets in a circuit with their connections.

    Args:
        circuit_name: Circuit name. Uses active circuit if empty.

    Returns:
        List of all nets with connected pins.
    """
    try:
        entry = manager.get(circuit_name) if circuit_name else manager.get_active()
        nets = []
        for name, net in entry.nets.items():
            pins = []
            for pin in net.pins:
                pins.append(f"{pin.part.ref}:{pin.num}({pin.name})")
            nets.append({
                "name": name,
                "connections": pins,
                "connection_count": len(pins),
            })
        return {
            "status": "ok",
            "circuit": entry.name,
            "nets": nets,
            "count": len(nets),
        }
    except (KeyError, RuntimeError) as e:
        return {"status": "error", "message": str(e)}


def create_bus(name: str, width: int) -> dict:
    """Create a bus (group of related nets) in the active circuit.

    Args:
        name: Bus name (e.g. "DATA", "ADDR"). Individual nets are named name0, name1, etc.
        width: Number of nets in the bus (e.g. 8 for an 8-bit data bus).

    Returns:
        Bus details with individual net names.
    """
    if not name or not name.strip():
        return {"status": "error", "message": "Bus name cannot be empty."}
    if width <= 0:
        return {"status": "error", "message": "Bus width must be a positive integer."}

    try:
        entry = manager.get_active()
        if name in entry.buses:
            return {"status": "error", "message": f"Bus '{name}' already exists."}

        bus = Bus(name, width, circuit=entry.circuit)
        entry.buses[name] = bus

        # Also register individual nets
        net_names = []
        for i, net in enumerate(bus):
            net_name = net.name
            entry.nets[net_name] = net
            net_names.append(net_name)

        return {
            "status": "created",
            "name": name,
            "width": width,
            "net_names": net_names,
            "message": f"Bus '{name}' with {width} nets created.",
        }
    except (RuntimeError, KeyError, ValueError) as e:
        return {"status": "error", "message": str(e)}


def add_power_nets() -> dict:
    """Add standard power nets (VCC, GND, +3V3, +5V) to the active circuit.

    Returns:
        List of created power nets.
    """
    try:
        entry = manager.get_active()
        power_nets = ["VCC", "GND", "+3V3", "+5V", "+12V"]
        created = []
        skipped = []

        for name in power_nets:
            if name in entry.nets:
                skipped.append(name)
            else:
                net = Net(name, circuit=entry.circuit)
                entry.nets[name] = net
                created.append(name)

        return {
            "status": "ok",
            "created": created,
            "skipped": skipped,
            "message": f"Power nets created: {created}. Already existed: {skipped}.",
        }
    except (RuntimeError, KeyError) as e:
        return {"status": "error", "message": str(e)}


def _find_pin(part, pin_id: str, ref: str):
    """Find a pin on a part by number or name. Returns pin or error dict."""
    for p in part.pins:
        if str(p.num) == str(pin_id) or p.name == pin_id:
            return p
    pin_list = [f"{p.num}({p.name})" for p in part.pins]
    return {"status": "error", "message": f"Pin '{pin_id}' not found on {ref}. Available: {pin_list}"}
