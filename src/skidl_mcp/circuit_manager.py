"""Manages circuit state across MCP tool calls.

Provides a singleton CircuitManager that maintains named SKiDL Circuit objects
with metadata, allowing multiple circuits to be managed in a single session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import skidl_mcp.skidl_quiet  # noqa: F401  (must precede any skidl import)
from skidl import Bus, Circuit, Net, Part


def part_library_name(part: Any, default: str | None = None) -> str | None:
    """Return a compact library name for a SKiDL part."""
    lib = getattr(part, "lib", None)
    if lib is None:
        return default

    filename = getattr(lib, "filename", None)
    if filename:
        return str(filename)

    name = getattr(lib, "name", None)
    if name:
        return str(name)

    return str(lib)


@dataclass
class CircuitEntry:
    """A named circuit with its SKiDL Circuit object and metadata."""

    name: str
    description: str
    circuit: Circuit
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parts: dict[str, Part] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)
    buses: dict[str, Bus] = field(default_factory=dict)
    # Phase B: design metadata that persists to disk alongside the structure.
    # ``requirements`` is free-form human intent; ``roles``/``interfaces`` are
    # reserved semantic annotations (populated by later phases); ``metadata``
    # carries unknown design.yaml keys through a load→save cycle unchanged.
    requirements: str = ""
    roles: dict[str, str] = field(default_factory=dict)
    interfaces: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Project directory this circuit was last saved to / loaded from ("" if it
    # has never been persisted). Records provenance; the manager's own
    # ``project_root`` drives the default save/load path.
    project_root: str = ""

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serializable summary of this circuit."""
        parts_info = []
        for ref, part in self.parts.items():
            parts_info.append({
                "ref": ref,
                "name": part.name,
                "value": str(v) if (v := getattr(part, "value", None)) is not None else None,
                "footprint": str(fp) if (fp := getattr(part, "footprint", None)) is not None else None,
                "library": part_library_name(part),
                "pin_count": len(part.pins),
            })

        nets_info = []
        for name, net in self.nets.items():
            pins = []
            for pin in net.pins:
                try:
                    pins.append(f"{pin.part.ref}:{pin.name}")
                except (AttributeError, TypeError):
                    pins.append("unknown:unknown")
            nets_info.append({
                "name": name,
                "connections": pins,
            })

        buses_info = []
        for name, bus in self.buses.items():
            buses_info.append({
                "name": name,
                "width": len(bus),
                "net_names": [n.name for n in bus],
            })

        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "parts_count": len(self.parts),
            "nets_count": len(self.nets),
            "buses_count": len(self.buses),
            "parts": parts_info,
            "nets": nets_info,
            "buses": buses_info,
        }


class CircuitManager:
    """Singleton manager for named SKiDL circuits.

    Maintains a dictionary of CircuitEntry objects and tracks which
    circuit is currently active.
    """

    def __init__(self) -> None:
        self._circuits: dict[str, CircuitEntry] = {}
        self._active: str | None = None
        self._project_root: str | None = None

    def reset(self) -> None:
        """Clear all circuits and reset state. Useful for testing."""
        self._circuits.clear()
        self._active = None
        self._project_root = None

    @property
    def active_name(self) -> str | None:
        return self._active

    @property
    def project_root(self) -> str | None:
        """Filesystem directory that is the current design's source of truth.

        Set by ``open_project``/``save_circuit``/``load_circuit`` (Phase B) so a
        later ``save_circuit()`` with no explicit path knows where to write.
        """
        return self._project_root

    @project_root.setter
    def project_root(self, value: str | None) -> None:
        self._project_root = value

    def install(self, entry: CircuitEntry, *, activate: bool = True) -> CircuitEntry:
        """Register a pre-built entry (e.g. one restored from disk).

        Replaces any existing circuit of the same name so loading from disk —
        the source of truth — overwrites a stale in-memory copy.
        """
        self._circuits[entry.name] = entry
        if activate:
            self._active = entry.name
        return entry

    def create(self, name: str, description: str = "") -> CircuitEntry:
        """Create a new named circuit and set it as active."""
        if name in self._circuits:
            raise ValueError(f"Circuit '{name}' already exists")
        circuit = Circuit()
        entry = CircuitEntry(name=name, description=description, circuit=circuit)
        self._circuits[name] = entry
        self._active = name
        return entry

    def get(self, name: str) -> CircuitEntry:
        """Get a circuit by name."""
        if name not in self._circuits:
            raise KeyError(f"Circuit '{name}' not found. Available: {list(self._circuits.keys())}")
        return self._circuits[name]

    def get_active(self) -> CircuitEntry:
        """Get the currently active circuit."""
        if self._active is None:
            raise RuntimeError("No active circuit. Create one first with create_circuit().")
        return self.get(self._active)

    def switch(self, name: str) -> CircuitEntry:
        """Switch the active circuit."""
        entry = self.get(name)
        self._active = name
        return entry

    def delete(self, name: str) -> None:
        """Delete a circuit by name."""
        if name not in self._circuits:
            raise KeyError(f"Circuit '{name}' not found")
        del self._circuits[name]
        if self._active == name:
            self._active = next(iter(self._circuits), None)

    def list_all(self) -> list[dict[str, Any]]:
        """List all circuits with basic metadata."""
        result = []
        for name, entry in self._circuits.items():
            result.append({
                "name": name,
                "description": entry.description,
                "created_at": entry.created_at,
                "parts_count": len(entry.parts),
                "nets_count": len(entry.nets),
                "is_active": name == self._active,
            })
        return result

    def find_part(self, ref: str, entry: CircuitEntry | None = None) -> Part:
        """Find a part by reference designator in the given or active circuit."""
        if entry is None:
            entry = self.get_active()
        if ref not in entry.parts:
            available = list(entry.parts.keys())
            raise KeyError(f"Part '{ref}' not found. Available: {available}")
        return entry.parts[ref]

    def find_net(self, name: str, entry: CircuitEntry | None = None) -> Net:
        """Find a net by name in the given or active circuit."""
        if entry is None:
            entry = self.get_active()
        if name not in entry.nets:
            available = list(entry.nets.keys())
            raise KeyError(f"Net '{name}' not found. Available: {available}")
        return entry.nets[name]


# Module-level singleton
manager = CircuitManager()
