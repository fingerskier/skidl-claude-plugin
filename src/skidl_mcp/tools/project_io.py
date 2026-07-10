"""Phase B: persist a circuit to / restore it from a project directory.

A *project directory* is the durable source of truth for a design across agent
sessions (the in-memory :data:`~skidl_mcp.circuit_manager.manager` is just a
cache). Layout::

    project/
      circuit.json   canonical structural model — the authoritative load source
      design.yaml    human-facing metadata (name, description, requirements, ...)
      circuit.py     generated SKiDL view (regeneration path; NOT the load format)
      artifacts/     generator outputs (netlists, BOMs, SVGs, ...)
      worlds/        reserved for simulation worlds (a later phase)

``circuit.json`` is deterministic and git-diffable: parts are natural-sorted by
ref (so ``R2`` precedes ``R10``), nets sorted by name, pins by ``(num, name)``;
there are no timestamps or random tags. Serializing the same in-memory circuit
twice therefore yields byte-identical text, and ``save → load → save`` is a
fixpoint.

**Security:** loading rebuilds the SKiDL Circuit and the manager's
parts/nets/buses indexes from ``circuit.json`` *alone*. It never imports or
executes ``circuit.py`` (or any Python), so opening/loading a project directory
cannot run arbitrary code. ``circuit.py`` is a convenience view for humans and
for high-fidelity regeneration against real KiCad libraries.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import skidl_mcp.skidl_quiet  # noqa: F401  (must precede any skidl import)
import yaml
from skidl import SKIDL, Bus, Circuit, Net, Part, Pin

from skidl_mcp.circuit_manager import CircuitEntry, manager, part_library_name
from skidl_mcp.tools.generate import circuit_to_python

SCHEMA_VERSION = 1

CIRCUIT_JSON = "circuit.json"
DESIGN_YAML = "design.yaml"
CIRCUIT_PY = "circuit.py"
ARTIFACTS_DIR = "artifacts"
WORLDS_DIR = "worlds"

# design.yaml keys owned by this module; everything else a human adds is carried
# through a load→save cycle verbatim via ``entry.metadata``.
_KNOWN_YAML_KEYS = {"schema_version", "name", "description", "created_at", "requirements"}

# Every way a hand-edited or corrupt project directory can be malformed, so the
# load tools turn it into a clean ``{status: error}`` instead of crashing: bad or
# wrong-shaped JSON (ValueError/TypeError/AttributeError/KeyError), bad YAML
# metadata (yaml.YAMLError), or a filesystem failure (OSError).
_LOAD_ERRORS = (ValueError, TypeError, KeyError, AttributeError, OSError, yaml.YAMLError)


# ── Deterministic ordering helpers ──────────────────────────────────────────


def _natural_key(text: str) -> tuple:
    """Sort key that orders embedded numbers numerically (R2 < R10 < R100).

    ``re.split`` on a capturing digit group always yields an odd-length list that
    alternates non-digit / digit tokens, so element *i* has the same type across
    every string — no int-vs-str comparison ever occurs.
    """
    return tuple(
        int(tok) if tok.isdigit() else tok
        for tok in re.split(r"(\d+)", text)
    )


def _pin_token_key(token: str) -> tuple:
    """Sort key for a ``"R1.2"`` net-connection token by (part ref, pin num).

    Splits on the *last* dot so hierarchical refs that embed a dot (``"sub.R1.2"``)
    still separate cleanly into (ref, pin num).
    """
    ref, _, num = token.rpartition(".")
    return (_natural_key(ref), _natural_key(num))


# ── Serialization: CircuitEntry -> plain dict / text ────────────────────────


def _pin_dict(pin: Any) -> dict:
    func = getattr(pin, "func", None)
    func_name = getattr(func, "name", None)  # IntEnum member name, e.g. "PASSIVE"
    return {
        "num": str(pin.num),
        "name": str(pin.name),
        "func": func_name if func_name else "",
    }


def _part_dict(ref: str, part: Any) -> dict:
    pins = [_pin_dict(p) for p in part.pins]
    pins.sort(key=lambda pd: (_natural_key(pd["num"]), pd["name"]))
    fields = getattr(part, "fields", {}) or {}
    return {
        "ref": ref,
        "library": part_library_name(part, "") or "",
        "name": str(part.name),
        "value": str(getattr(part, "value", "") or ""),
        "footprint": str(getattr(part, "footprint", "") or ""),
        "description": str(getattr(part, "description", "") or ""),
        "fields": {str(k): str(v) for k, v in sorted(fields.items())},
        "pins": pins,
    }


def _net_dict(name: str, net: Any) -> dict:
    tokens = []
    for pin in net.pins:
        try:
            tokens.append(f"{pin.part.ref}.{pin.num}")
        except (AttributeError, TypeError):
            continue
    tokens.sort(key=_pin_token_key)
    return {"name": name, "pins": tokens}


def serialize_entry(entry: CircuitEntry) -> dict:
    """Return the canonical, deterministic structural model for ``entry``.

    The result is JSON-ready and stable: parts natural-sorted by ref, nets by
    name, pins by ``(num, name)``, and no timestamps or random tags anywhere.
    """
    parts = [_part_dict(ref, part) for ref, part in entry.parts.items()]
    parts.sort(key=lambda pd: _natural_key(pd["ref"]))

    nets = [_net_dict(name, net) for name, net in entry.nets.items()]
    nets.sort(key=lambda nd: _natural_key(nd["name"]))

    buses = []
    for name, bus in entry.buses.items():
        buses.append({
            "name": name,
            "width": len(bus),
            "nets": [n.name for n in bus],
        })
    buses.sort(key=lambda bd: _natural_key(bd["name"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "name": entry.name,
        "description": entry.description,
        "parts": parts,
        "nets": nets,
        "buses": buses,
        # Reserved semantic annotations (empty until a later phase populates them).
        "roles": {k: entry.roles[k] for k in sorted(entry.roles)},
        "interfaces": {k: entry.interfaces[k] for k in sorted(entry.interfaces)},
    }


def circuit_json_text(data: dict) -> str:
    """Render a serialized model as deterministic JSON text with a trailing newline."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def design_yaml_text(entry: CircuitEntry) -> str:
    """Render the human-facing metadata layer as deterministic YAML text.

    Known keys are emitted in a fixed order; any unknown keys a human added
    (carried in ``entry.metadata``) follow in sorted order so the file is stable.
    """
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "name": entry.name,
        "description": entry.description,
        "created_at": entry.created_at,
        "requirements": entry.requirements,
    }
    for key in sorted(entry.metadata):
        if key not in doc:
            doc[key] = entry.metadata[key]
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=True)


# ── Restoration: dict -> CircuitEntry ───────────────────────────────────────


def _func_from_name(name: str | None):
    """Map a stored pin-function name back to a ``Pin.types`` member, or None."""
    if not name:
        return None
    return getattr(Pin.types, name, None)


def _restore_part(part_data: dict, circuit: Circuit) -> Part:
    pins = []
    for pd in part_data.get("pins", []):
        kwargs = {"num": pd["num"], "name": pd.get("name", "")}
        func = _func_from_name(pd.get("func"))
        if func is not None:
            kwargs["func"] = func
        pins.append(Pin(**kwargs))
    part = Part(name=part_data["name"], tool=SKIDL, pins=pins,
                circuit=circuit, ref=part_data["ref"])
    if part_data.get("value"):
        part.value = part_data["value"]
    if part_data.get("footprint"):
        part.footprint = part_data["footprint"]
    if part_data.get("description"):
        part.description = part_data["description"]
    fields = part_data.get("fields") or {}
    if fields:
        part.fields.update(fields)
    return part


def restore_entry(data: dict, *, circuit: Circuit | None = None) -> CircuitEntry:
    """Rebuild a fully-indexed :class:`CircuitEntry` from a serialized model.

    Reconstructs the SKiDL Circuit plus the ``parts``/``nets``/``buses`` indexes
    the tools read from, so a restored circuit behaves exactly like one built
    interactively. Parts are recreated as library-independent bare parts from the
    stored pin table, so this works offline with no KiCad install.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"circuit.json must be a JSON object, got {type(data).__name__}."
        )
    if circuit is None:
        circuit = Circuit()

    entry = CircuitEntry(
        name=data.get("name", "circuit"),
        description=data.get("description", ""),
        circuit=circuit,
    )

    # 1) Parts (with their pins) first — nets connect to their pins.
    for part_data in data.get("parts", []):
        part = _restore_part(part_data, circuit)
        entry.parts[part.ref] = part

    # 2) Buses next: each Bus creates its own member nets; register those so the
    #    net pass below reuses them instead of creating duplicates. Member nets are
    #    reconstructed from SKiDL's deterministic (name, width) auto-naming in this
    #    fresh circuit; the stored ``bus_data["nets"]`` names are retained in
    #    circuit.json for readability/forward-compat but are not needed to restore.
    for bus_data in data.get("buses", []):
        bus = Bus(bus_data["name"], int(bus_data.get("width", 0)), circuit=circuit)
        entry.buses[bus_data["name"]] = bus
        for net in bus:
            entry.nets[net.name] = net

    # 3) Nets: reuse a bus-created net if present, else make a standalone one,
    #    then wire up the pins recorded for it.
    for net_data in data.get("nets", []):
        name = net_data["name"]
        net = entry.nets.get(name)
        if net is None:
            net = Net(name, circuit=circuit)
            entry.nets[name] = net
        for token in net_data.get("pins", []):
            ref, _, num = token.rpartition(".")
            part = entry.parts.get(ref)
            if part is None:
                continue
            matches = [p for p in part.pins if str(p.num) == num]
            if matches:
                net += matches[0]

    entry.roles = dict(data.get("roles") or {})
    entry.interfaces = dict(data.get("interfaces") or {})
    return entry


# ── Project directory read/write ────────────────────────────────────────────


def save_project(entry: CircuitEntry, root: Path) -> dict:
    """Write ``entry`` to the project directory ``root`` and return a file map.

    Writes ``circuit.json`` (authoritative), ``design.yaml`` (metadata) and a
    ``circuit.py`` view, and ensures the ``artifacts/`` and ``worlds/`` skeleton
    dirs exist. All text is written with ``newline=""`` so on-disk bytes are
    byte-identical to the deterministic text (no CRLF translation).
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / ARTIFACTS_DIR).mkdir(exist_ok=True)
    (root / WORLDS_DIR).mkdir(exist_ok=True)

    data = serialize_entry(entry)
    (root / CIRCUIT_JSON).write_text(circuit_json_text(data), encoding="utf-8", newline="")
    (root / DESIGN_YAML).write_text(design_yaml_text(entry), encoding="utf-8", newline="")
    try:
        (root / CIRCUIT_PY).write_text(circuit_to_python(entry), encoding="utf-8", newline="")
    except Exception:
        # circuit.py is a best-effort view; never fail a save over it.
        pass

    return {
        "root": str(root),
        "circuit_json": str(root / CIRCUIT_JSON),
        "design_yaml": str(root / DESIGN_YAML),
        "circuit_py": str(root / CIRCUIT_PY),
    }


def load_project(root: Path) -> CircuitEntry:
    """Read a project directory and return a restored :class:`CircuitEntry`.

    Structure comes from ``circuit.json`` (required); ``design.yaml`` (optional)
    supplies the human metadata layer — its ``description``/``requirements`` win
    when present, and any unknown keys are preserved on ``entry.metadata`` so a
    subsequent save round-trips them.
    """
    root = Path(root)
    circuit_json = root / CIRCUIT_JSON
    if not circuit_json.is_file():
        raise FileNotFoundError(f"No {CIRCUIT_JSON} in project directory '{root}'.")

    data = json.loads(circuit_json.read_text(encoding="utf-8"))
    entry = restore_entry(data)

    design_yaml = root / DESIGN_YAML
    if design_yaml.is_file():
        meta = yaml.safe_load(design_yaml.read_text(encoding="utf-8")) or {}
        if isinstance(meta, dict):
            if meta.get("description"):
                entry.description = str(meta["description"])
            entry.requirements = str(meta.get("requirements", "") or "")
            if meta.get("created_at"):
                entry.created_at = str(meta["created_at"])
            entry.metadata = {k: v for k, v in meta.items() if k not in _KNOWN_YAML_KEYS}

    return entry


# ── MCP tool entry points ───────────────────────────────────────────────────


def _summary(entry: CircuitEntry) -> dict:
    return {
        "name": entry.name,
        "parts": len(entry.parts),
        "nets": len(entry.nets),
        "buses": len(entry.buses),
    }


def open_project(path: str) -> dict:
    """Open a project directory as the active design's source of truth.

    Creates the ``artifacts/`` and ``worlds/`` skeleton if missing, records the
    directory so a later ``save_circuit()`` needs no path, and — if the directory
    already contains a ``circuit.json`` — loads that design and makes it active.
    Loading never executes ``circuit.py`` or any project code.

    Args:
        path: Project directory (created if it does not exist).

    Returns:
        ``{status, path, loaded, ...}``; ``loaded`` is True when an existing
        design was read from disk.
    """
    if not path or not path.strip():
        return {"status": "error", "message": "Project path cannot be empty."}

    root = Path(path).expanduser().resolve()
    if root.exists() and not root.is_dir():
        return {"status": "error", "message": f"Project path '{root}' is not a directory."}

    # mkdir can still fail even when the file-vs-dir guard passes — e.g. the path
    # is *under* an existing file, or the parent is read-only. Report it cleanly.
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / ARTIFACTS_DIR).mkdir(exist_ok=True)
        (root / WORLDS_DIR).mkdir(exist_ok=True)
    except OSError as e:
        return {"status": "error", "message": f"Could not create project directory '{root}': {e}"}
    manager.project_root = str(root)

    if (root / CIRCUIT_JSON).is_file():
        try:
            entry = load_project(root)
        except _LOAD_ERRORS as e:
            return {"status": "error", "message": f"Failed to load project: {e}"}
        manager.install(entry, activate=True)
        return {
            "status": "ok",
            "path": str(root),
            "loaded": True,
            "active": entry.name,
            "summary": _summary(entry),
            "message": f"Opened project '{root}' and loaded circuit '{entry.name}'.",
        }

    return {
        "status": "ok",
        "path": str(root),
        "loaded": False,
        "message": (
            f"Opened project '{root}'. No circuit.json yet — build a circuit and "
            "call save_circuit() to write it here."
        ),
    }


def save_circuit(path: str | None = None) -> dict:
    """Save the active circuit to a project directory (its source of truth).

    Writes ``circuit.json`` (authoritative structure), ``design.yaml`` (metadata),
    and a ``circuit.py`` view. ``circuit.json`` is deterministic and git-diffable,
    and saving the same circuit twice produces byte-identical output.

    Args:
        path: Project directory. Defaults to the directory from the most recent
            ``open_project``/``save_circuit``/``load_circuit``.

    Returns:
        ``{status, path, files, summary}``.
    """
    root = (path or "").strip() or manager.project_root
    if not root:
        return {
            "status": "error",
            "message": "No project path. Pass path= or call open_project() first.",
        }

    try:
        entry = manager.get_active()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    root_path = Path(root).expanduser().resolve()
    if root_path.exists() and not root_path.is_dir():
        return {"status": "error", "message": f"Project path '{root_path}' is not a directory."}

    try:
        files = save_project(entry, root_path)
    except OSError as e:
        return {"status": "error", "message": f"Failed to save project: {e}"}

    entry.project_root = str(root_path)
    manager.project_root = str(root_path)
    return {
        "status": "ok",
        "path": str(root_path),
        "files": files,
        "summary": _summary(entry),
        "message": f"Saved circuit '{entry.name}' to project '{root_path}'.",
    }


def load_circuit(path: str | None = None) -> dict:
    """Load a circuit from a project directory, making it the active design.

    Structure is read from ``circuit.json`` only — ``circuit.py`` is never
    imported or executed — so loading is safe and works offline. An in-memory
    circuit of the same name is replaced (disk is the source of truth).

    Args:
        path: Project directory. Defaults to the current project directory.

    Returns:
        ``{status, path, active, summary}``.
    """
    root = (path or "").strip() or manager.project_root
    if not root:
        return {
            "status": "error",
            "message": "No project path. Pass path= or call open_project() first.",
        }

    root_path = Path(root).expanduser().resolve()
    try:
        entry = load_project(root_path)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}
    except _LOAD_ERRORS as e:
        return {"status": "error", "message": f"Failed to load project: {e}"}

    entry.project_root = str(root_path)
    manager.install(entry, activate=True)
    manager.project_root = str(root_path)
    return {
        "status": "ok",
        "path": str(root_path),
        "active": entry.name,
        "summary": _summary(entry),
        "message": f"Loaded circuit '{entry.name}' from project '{root_path}'.",
    }
