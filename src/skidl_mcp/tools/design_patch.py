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

from skidl_mcp.tools.nets import _find_pins


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
    return errors
