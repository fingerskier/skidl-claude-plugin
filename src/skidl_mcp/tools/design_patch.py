"""Phase C: declarative multi-entity design patches.

``apply_design_patch`` applies a whole batch of part / net / connection / role /
interface edits in one call, replacing many low-level tool round-trips. Semantics
are *merge* (create-or-update; net pins added) with destructive edits only through
explicit named fields (``remove_parts`` / ``remove_nets`` / ``disconnect`` /
per-net ``pins_mode: "set"``). Application is atomic: the whole patch is validated
first (nothing mutated on any error), and a snapshot taken via the Phase B
serializer is restored if a mutation throws despite validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from skidl import KICAD, Circuit, Net, Part

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import project_io
from skidl_mcp.tools.nets import _find_pins
from skidl_mcp.tools.project_io import restore_entry, serialize_entry


class PatchError(ValueError):
    """A design patch is malformed (bad shape/types) before any semantic check."""


@dataclass
class PartPatch:
    ref: str
    lib: str = ""
    name: str = ""
    value: str = ""
    footprint: str = ""
    role: str = ""
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class NetPatch:
    name: str
    role: str = ""
    pins: list[str] = field(default_factory=list)
    pins_mode: str = "add"


@dataclass
class InterfacePatch:
    name: str
    type: str = ""
    nets: dict[str, str] = field(default_factory=dict)


@dataclass
class DesignPatch:
    parts: list[PartPatch] = field(default_factory=list)
    nets: list[NetPatch] = field(default_factory=list)
    interfaces: list[InterfacePatch] = field(default_factory=list)
    remove_parts: list[str] = field(default_factory=list)
    remove_nets: list[str] = field(default_factory=list)
    disconnect: list[str] = field(default_factory=list)

    @classmethod
    def from_obj(cls, patch: Any) -> "DesignPatch":
        if isinstance(patch, str):
            try:
                patch = yaml.safe_load(patch)
            except yaml.YAMLError as e:
                raise PatchError(f"Patch is not valid YAML/JSON: {e}") from e
        if patch is None:
            patch = {}
        if not isinstance(patch, dict):
            raise PatchError(f"Patch must be a mapping, got {type(patch).__name__}.")
        return cls(
            parts=[_part_patch(p) for p in _as_list(patch, "parts")],
            nets=[_net_patch(n) for n in _as_list(patch, "nets")],
            interfaces=[_iface_patch(i) for i in _as_list(patch, "interfaces")],
            remove_parts=[_as_ref(x, "remove_parts") for x in _as_list(patch, "remove_parts")],
            remove_nets=[_as_ref(x, "remove_nets") for x in _as_list(patch, "remove_nets")],
            disconnect=[_as_ref(x, "disconnect") for x in _as_list(patch, "disconnect")],
        )


# ── Parse helpers (raise PatchError on bad shape) ───────────────────────────


def _as_list(patch: dict, key: str) -> list:
    val = patch.get(key, [])
    if val is None:
        return []
    if not isinstance(val, list):
        raise PatchError(f"'{key}' must be a list, got {type(val).__name__}.")
    return val


def _as_ref(x: Any, key: str) -> str:
    if not isinstance(x, str) or not x.strip():
        raise PatchError(f"'{key}' entries must be non-empty strings, got {x!r}.")
    return x


def _require_mapping(x: Any, key: str) -> dict:
    if not isinstance(x, dict):
        raise PatchError(f"Each '{key}' entry must be a mapping, got {type(x).__name__}.")
    return x


def _require_str(d: dict, k: str, ctx: str) -> str:
    v = d.get(k, "")
    if not isinstance(v, str) or not v.strip():
        raise PatchError(f"{ctx} requires a non-empty string '{k}'.")
    return v


def _part_patch(x: Any) -> PartPatch:
    d = _require_mapping(x, "parts")
    ref = _require_str(d, "ref", "part patch")
    fields = d.get("fields", {}) or {}
    if not isinstance(fields, dict):
        raise PatchError(f"part {ref}: 'fields' must be a mapping.")
    return PartPatch(
        ref=ref,
        lib=str(d.get("lib", "") or ""),
        name=str(d.get("name", "") or ""),
        value=str(d.get("value", "") or ""),
        footprint=str(d.get("footprint", "") or ""),
        role=str(d.get("role", "") or ""),
        fields={str(k): str(v) for k, v in fields.items()},
    )


def _net_patch(x: Any) -> NetPatch:
    d = _require_mapping(x, "nets")
    name = _require_str(d, "name", "net patch")
    pins = d.get("pins", []) or []
    if not isinstance(pins, list) or not all(isinstance(p, str) for p in pins):
        raise PatchError(f"net {name}: 'pins' must be a list of 'REF.pin' strings.")
    mode = str(d.get("pins_mode", "add") or "add")
    if mode not in ("add", "set"):
        raise PatchError(f"net {name}: pins_mode must be 'add' or 'set', got '{mode}'.")
    return NetPatch(name=name, role=str(d.get("role", "") or ""), pins=list(pins), pins_mode=mode)


def _iface_patch(x: Any) -> InterfacePatch:
    d = _require_mapping(x, "interfaces")
    name = _require_str(d, "name", "interface patch")
    net_map = d.get("nets", {}) or {}
    if not isinstance(net_map, dict):
        raise PatchError(f"interface {name}: 'nets' must be a mapping of logical->net.")
    return InterfacePatch(
        name=name,
        type=str(d.get("type", "") or ""),
        nets={str(k): str(v) for k, v in net_map.items()},
    )


# ── Validation ────────────────────────────────────────────────────────────


def _split_token(token: str) -> tuple[str, str]:
    """Split a 'REF.pin' token on the last dot into (ref, pin)."""
    ref, _, pin = token.rpartition(".")
    return ref, pin


def validate_patch(entry, patch: DesignPatch) -> list[str]:
    """Return actionable errors for anything that would fail; empty == applicable.

    Nets/interfaces may reference parts/nets this same patch creates, so those are
    treated as present. Pin existence on an *already-present* part is checked here;
    pins on a to-be-created part are deferred to apply time (can't resolve offline).
    """
    errors: list[str] = []
    created_parts = {p.ref for p in patch.parts}
    created_nets = {n.name for n in patch.nets}

    for pp in patch.parts:
        if pp.ref not in entry.parts and not (pp.lib and pp.name):
            errors.append(
                f"Part '{pp.ref}' does not exist and cannot be created: provide "
                f"both 'lib' and 'name'."
            )

    for np in patch.nets:
        for token in np.pins:
            ref, pin = _split_token(token)
            if not ref or not pin:
                errors.append(f"Bad pin token '{token}': expected 'REF.pin'.")
                continue
            if ref in entry.parts:
                found = _find_pins(entry.parts[ref], pin, ref)
                if isinstance(found, dict):
                    errors.append(f"Token '{token}': {found['message']}")
            elif ref not in created_parts:
                errors.append(
                    f"Net '{np.name}' references pin on unknown part '{ref}'. "
                    f"Available: {list(entry.parts.keys())}"
                )

    for token in patch.disconnect:
        ref, pin = _split_token(token)
        if ref not in entry.parts:
            errors.append(
                f"disconnect '{token}': unknown part '{ref}'. "
                f"Available: {list(entry.parts.keys())}"
            )
            continue
        found = _find_pins(entry.parts[ref], pin, ref)
        if isinstance(found, dict):
            errors.append(found["message"])

    for ref in patch.remove_parts:
        if ref not in entry.parts:
            errors.append(
                f"remove_parts: part '{ref}' not found. Available: {list(entry.parts.keys())}"
            )

    for name in patch.remove_nets:
        if name not in entry.nets:
            errors.append(
                f"remove_nets: net '{name}' not found. Available: {list(entry.nets.keys())}"
            )

    for ip in patch.interfaces:
        for logical, net_name in ip.nets.items():
            if net_name not in entry.nets and net_name not in created_nets:
                errors.append(
                    f"Interface '{ip.name}' maps '{logical}' to unknown net "
                    f"'{net_name}'. Available: {list(entry.nets.keys())}"
                )

    # Cross-field consistency: an operation must not target an entity this same
    # patch removes earlier in the apply order (unless a later phase re-creates it).
    removed_parts = set(patch.remove_parts)
    removed_nets = set(patch.remove_nets)

    for token in patch.disconnect:
        ref, _ = _split_token(token)
        if ref in removed_parts:
            errors.append(
                f"disconnect '{token}': part '{ref}' is also in remove_parts; "
                f"cannot disconnect a pin on a part the same patch removes."
            )

    for np in patch.nets:
        for token in np.pins:
            ref, _ = _split_token(token)
            if ref in removed_parts and ref not in created_parts:
                errors.append(
                    f"Net '{np.name}' references pin on part '{ref}' which the same "
                    f"patch removes and does not re-create."
                )

    for ip in patch.interfaces:
        for logical, net_name in ip.nets.items():
            if net_name in removed_nets and net_name not in created_nets:
                errors.append(
                    f"Interface '{ip.name}' maps '{logical}' to net '{net_name}' "
                    f"which the same patch removes and does not re-create."
                )
    return errors


# ── Application ──────────────────────────────────────────────────────────


class _ApplyError(RuntimeError):
    """A mutation failed after validation — triggers snapshot rollback."""


def _empty_diff() -> dict:
    return {
        "parts_added": [], "parts_updated": [], "parts_removed": [],
        "nets_created": [], "nets_removed": [],
        "connections_added": 0, "connections_removed": 0,
        "roles_set": [], "interfaces_set": [],
    }


def apply_design_patch(patch, dry_run: bool = False) -> dict:
    """Apply a declarative, atomic, multi-entity change to the active circuit.

    Args:
        patch: a mapping or a YAML/JSON string (see module docstring for the shape).
        dry_run: when True, validate and compute the diff but mutate nothing.

    Returns the diff contract ``{status, applied, warnings[, dry_run, rolled_back,
    errors]}``. A validation error mutates nothing; a mid-apply throw restores the
    pre-patch snapshot and sets ``rolled_back: True``.
    """
    try:
        entry = manager.get_active()
    except RuntimeError as e:
        return {"status": "error", "errors": [str(e)], "applied": _empty_diff()}

    try:
        parsed = DesignPatch.from_obj(patch)
    except PatchError as e:
        return {"status": "error", "errors": [str(e)], "applied": _empty_diff()}

    errors = validate_patch(entry, parsed)
    if errors:
        return {"status": "error", "errors": errors, "applied": _empty_diff()}

    diff = _empty_diff()
    warnings: list[str] = []

    if dry_run:
        # Apply to a throwaway rebuilt from the snapshot; the live circuit is
        # never touched. Part creation (needs KiCad) still runs on the copy.
        temp = project_io.restore_entry(project_io.serialize_entry(entry), circuit=Circuit())
        try:
            _apply(temp, parsed, diff, warnings)
        except Exception as e:  # noqa: BLE001 — symmetric with the live path below
            return {"status": "error", "errors": [str(e)], "applied": _empty_diff()}
        return {"status": "ok", "applied": diff, "warnings": warnings, "dry_run": True}

    snapshot = serialize_entry(entry)
    try:
        _apply(entry, parsed, diff, warnings)
    except Exception as e:  # noqa: BLE001 — validation should prevent this; defend anyway
        _rollback(entry, snapshot)
        return {
            "status": "error", "rolled_back": True,
            "errors": [f"Patch failed mid-apply and was rolled back: {e}"],
            "applied": _empty_diff(),
        }
    return {"status": "ok", "applied": diff, "warnings": warnings}


def _rollback(entry, snapshot: dict) -> None:
    """Restore the active circuit to ``snapshot`` (taken before mutation).

    ``_apply`` mutates ``entry`` in place (it *is* the live circuit, not a copy),
    so a partial failure leaves ``entry`` — and any reference a caller already
    holds to it, e.g. from an earlier ``manager.get_active()`` — part-mutated.
    Rebuilding a fresh entry and swapping it into the manager by name would not
    fix that stale reference, so instead we rebuild from the snapshot and copy
    the restored structural state back onto the *same* ``entry`` object.
    """
    restored = restore_entry(snapshot, circuit=Circuit())
    entry.circuit = restored.circuit
    entry.name = restored.name
    entry.description = restored.description
    entry.parts = restored.parts
    entry.nets = restored.nets
    entry.buses = restored.buses
    entry.roles = restored.roles
    entry.interfaces = restored.interfaces
    # created_at/requirements/metadata/project_root are not part of the
    # structural snapshot (serialize_entry drops them) — they're already
    # untouched on `entry`, so nothing to restore for those.
    manager.install(entry, activate=True)


# ── Mutation (all operate on the passed entry; order is deterministic) ──────


def _apply(entry, patch: DesignPatch, diff: dict, warnings: list[str]) -> None:
    _apply_remove_parts(entry, patch, diff)      # Task 4
    _apply_remove_nets(entry, patch, diff)       # Task 4
    _apply_disconnect(entry, patch, diff)        # Task 4
    _apply_parts(entry, patch, diff)
    _apply_nets(entry, patch, diff, warnings)
    _apply_roles(entry, patch, diff)
    _apply_interfaces(entry, patch, diff)


def _apply_parts(entry, patch: DesignPatch, diff: dict) -> None:
    for pp in patch.parts:
        if pp.ref in entry.parts:
            _update_part(entry.parts[pp.ref], pp, pp.ref, diff)
        else:
            kwargs = {"tool": KICAD, "ref": pp.ref}
            if pp.value:
                kwargs["value"] = pp.value
            if pp.footprint:
                kwargs["footprint"] = pp.footprint
            try:
                part = Part(pp.lib, pp.name, circuit=entry.circuit, **kwargs)
            except Exception as e:  # noqa: BLE001 — external-library boundary
                raise _ApplyError(
                    f"Could not create part '{pp.ref}' from '{pp.lib}:{pp.name}': {e}"
                ) from e
            if pp.fields:
                part.fields.update(pp.fields)
            entry.parts[pp.ref] = part
            diff["parts_added"].append(pp.ref)


def _update_part(part, pp: PartPatch, ref: str, diff: dict) -> None:
    changed = False
    if pp.value and str(getattr(part, "value", "") or "") != pp.value:
        part.value = pp.value
        changed = True
    if pp.footprint and str(getattr(part, "footprint", "") or "") != pp.footprint:
        part.footprint = pp.footprint
        changed = True
    for k, v in pp.fields.items():
        if str((part.fields or {}).get(k, "")) != v:
            part.fields[k] = v
            changed = True
    if changed:
        diff["parts_updated"].append(ref)


def _apply_nets(entry, patch: DesignPatch, diff: dict, warnings: list[str]) -> None:
    for np in patch.nets:
        net = entry.nets.get(np.name)
        if net is None:
            net = Net(np.name, circuit=entry.circuit)
            entry.nets[np.name] = net
            diff["nets_created"].append(np.name)
        added = _connect_net_pins(entry, net, np, warnings)
        diff["connections_added"] += added
        if np.pins_mode == "set":
            diff["connections_removed"] += _prune_net_pins(net, entry, np)


def _connect_net_pins(entry, net, np: NetPatch, warnings: list[str]) -> int:
    """Connect each listed pin not already on ``net``; return count added."""
    added = 0
    for token in np.pins:
        ref, pin_id = _split_token(token)
        part = entry.parts.get(ref)
        if part is None:  # created earlier in this same _apply pass
            raise _ApplyError(f"net {np.name}: part '{ref}' missing at connect time.")
        found = _find_pins(part, pin_id, ref)
        if isinstance(found, dict):
            raise _ApplyError(found["message"])
        if len(found) > 1:
            warnings.append(
                f"Pin '{pin_id}' matched {len(found)} pins on {ref}; connected all.")
        for pin in found:
            if not any(p is pin for p in net.pins):
                net += pin
                added += 1
    return added


def _apply_roles(entry, patch: DesignPatch, diff: dict) -> None:
    for pp in patch.parts:
        if pp.role:
            key = f"part:{pp.ref}"
            if entry.roles.get(key) != pp.role:
                entry.roles[key] = pp.role
                diff["roles_set"].append(key)
    for np in patch.nets:
        if np.role:
            key = f"net:{np.name}"
            if entry.roles.get(key) != np.role:
                entry.roles[key] = np.role
                diff["roles_set"].append(key)


def _apply_interfaces(entry, patch: DesignPatch, diff: dict) -> None:
    for ip in patch.interfaces:
        value = {"type": ip.type, "nets": dict(ip.nets)}
        if entry.interfaces.get(ip.name) != value:
            entry.interfaces[ip.name] = value
            diff["interfaces_set"].append(ip.name)


# ── Removal stubs (Task 4 implements these; harmless no-ops for now) ───────


def _apply_remove_parts(entry, patch: DesignPatch, diff: dict) -> None:
    for ref in patch.remove_parts:
        part = entry.parts.get(ref)
        if part is None:  # already removed (e.g. duplicate ref) — idempotent no-op
            continue
        for pin in part.pins:
            pin.disconnect()
        entry.circuit.rmv_parts(part)
        del entry.parts[ref]
        # Purge the annotation layer too, so a later part reusing this ref does
        # not silently inherit the deleted part's role (symmetric with B1's
        # graph/index sync). A same-patch re-create re-sets its role in step 4.
        entry.roles.pop(f"part:{ref}", None)
        diff["parts_removed"].append(ref)


def _apply_remove_nets(entry, patch: DesignPatch, diff: dict) -> None:
    for name in patch.remove_nets:
        net = entry.nets.get(name)
        if net is None:  # already removed (e.g. duplicate ref) — idempotent no-op
            continue
        for pin in list(net.pins):
            pin.disconnect()
        entry.circuit.rmv_nets(net)  # keep the SKiDL graph in sync with the index
        del entry.nets[name]
        # Keep the bus layer in sync too (B4): a removed net that was a bus member
        # must leave the bus, else serialize_entry emits a bus listing a net absent
        # from the top-level nets section and restore resurrects it (same desync
        # class as B1's graph/index sync).
        _unbus_net(entry, net)
        # Keep the annotation layer in sync: drop the net's role and any interface
        # net-mapping that pointed at it (interfaces are kept even if emptied, to
        # avoid a second, unnamed destructive edit — see spec §2).
        entry.roles.pop(f"net:{name}", None)
        _purge_net_from_interfaces(entry, name)
        diff["nets_removed"].append(name)


def _purge_net_from_interfaces(entry, net_name: str) -> None:
    """Drop any interface logical->net mapping that points at ``net_name``."""
    for iface in entry.interfaces.values():
        mapping = iface.get("nets")
        if isinstance(mapping, dict):
            for logical in [k for k, v in mapping.items() if v == net_name]:
                del mapping[logical]


def _unbus_net(entry, net) -> None:
    """Remove ``net`` from any bus that holds it (B4).

    SKiDL's ``Bus`` exposes its members as a plain ``bus.nets`` list with no
    removal method, so we rebuild that list without ``net``; ``len(bus)`` and
    iteration follow the reassignment. Match by identity — ``net`` is the same
    object the index and the bus both reference. A bus emptied by this is left in
    place rather than deleted: dropping a named bus would be a second, unnamed
    destructive edit, mirroring how emptied interfaces are kept (spec §2)."""
    for bus in entry.buses.values():
        if any(member is net for member in bus.nets):
            bus.nets = [member for member in bus.nets if member is not net]


def _apply_disconnect(entry, patch: DesignPatch, diff: dict) -> None:
    removed = 0
    for token in patch.disconnect:
        ref, pin_id = _split_token(token)
        found = _find_pins(entry.parts[ref], pin_id, ref)
        if isinstance(found, dict):  # validated already; defend anyway
            raise _ApplyError(found["message"])
        for pin in found:
            if pin.is_connected():
                pin.disconnect()
                removed += 1
    diff["connections_removed"] += removed


def _prune_net_pins(net, entry, np: NetPatch) -> int:
    """Disconnect pins currently on ``net`` that the patch's pin list omits."""
    keep = set()
    for token in np.pins:
        ref, pin_id = _split_token(token)
        part = entry.parts.get(ref)
        if part is None:
            continue
        found = _find_pins(part, pin_id, ref)
        if isinstance(found, list):
            keep.update(id(p) for p in found)
    removed = 0
    for pin in list(net.pins):
        if id(pin) not in keep:
            pin.disconnect()
            removed += 1
    return removed
