# Phase C — Declarative Design Patch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `apply_design_patch` (one declarative, atomic, multi-entity circuit edit) and `inspect_design` (a compact filtered read-only view) as MCP tools, cutting agent tool-call noise while keeping every existing low-level tool working.

**Architecture:** A new `tools/design_patch.py` holds a stdlib-dataclass schema (`DesignPatch.from_obj` parses a dict *or* a YAML string), a pure validation pass (`validate_patch`), and an atomic applier (`apply_design_patch`). The applier validates the whole patch first (nothing mutated on error), snapshots the active circuit with the Phase B serializer (`serialize_entry`), applies mutations in a fixed order using primitives the low-level tools already use (`Net`, `net += pin`, `_find_pins`, `pin.disconnect()`), and restores the snapshot (`restore_entry`) if a mutation throws despite validation. A separate `tools/inspect.py` holds `inspect_design`. `server.py` gains two `@mcp.tool()` wrappers.

**Tech Stack:** Python 3.10+, SKiDL 2.x, PyYAML (already a dependency), FastMCP (server layer only — not imported by tests), pytest.

## Global Constraints

- **Python 3.10+**; use `from __future__ import annotations` at the top of every new module (matches the codebase).
- **No Pydantic, no FastMCP in library/test code.** Neither is importable in the test interpreter. The patch schema is **stdlib `dataclasses`**; only `yaml` may be imported for parsing. `server.py` is the *only* file that imports `fastmcp`.
- **Offline-first tests.** The core test suite must pass with **no KiCad install**. Build parts in tests as bare parts: `Part(name="R", tool=SKIDL, pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")], circuit=entry.circuit, ref="R1")`. Only part *creation from a KiCad library* (`lib`+`name`) needs KiCad; gate any such test with `@pytest.mark.skipif` on KiCad availability, following `tests/test_integration_kicad.py`.
- **Merge + explicit removals only.** Default behavior creates-or-updates; destructive edits happen *only* via `remove_parts`, `remove_nets`, `disconnect`, and per-net `pins_mode: "set"`. There is **no** global `replace` mode.
- **Idempotent.** Re-applying an already-applied merge patch returns an all-empty diff (no counted changes).
- **Atomic.** A validation error mutates nothing. A mid-apply throw restores the pre-patch snapshot and reports `rolled_back: true`.
- **TDD, red/green, commit per task.** Run `python -m pytest -q` between steps. Baseline before this plan: **127 tests passing** — that number only goes up, never breaks.
- Pin token grammar: `REF.pin`, split on the **last** dot (`rpartition(".")`); `pin` is a number or name resolved by `nets._find_pins`. Multi-unit (`U1A.OUT`) is out of scope.

---

## File Structure

- **Create `src/skidl_mcp/tools/design_patch.py`** — patch dataclasses, `PatchError`, `DesignPatch.from_obj`, `validate_patch`, `apply_design_patch`, and private `_apply`/`_rollback`/`_empty_diff` helpers. One responsibility: turn a declarative patch into an atomic circuit mutation.
- **Create `src/skidl_mcp/tools/inspect.py`** — `inspect_design`. One responsibility: a filtered read-only projection of the active circuit.
- **Create `tests/test_design_patch.py`** — all patch tests.
- **Create `tests/test_inspect_design.py`** — all inspect tests.
- **Modify `src/skidl_mcp/server.py`** — add `design_patch, inspect` to the tools import (line 13) and two `@mcp.tool()` wrappers.
- **Modify `README.md`** — document the two new tools.

---

## Task 1: Patch schema + parser

**Files:**
- Create: `src/skidl_mcp/tools/design_patch.py`
- Test: `tests/test_design_patch.py`

**Interfaces:**
- Produces: `PatchError(ValueError)`; dataclasses `PartPatch(ref, lib="", name="", value="", footprint="", role="", fields={})`, `NetPatch(name, role="", pins=[], pins_mode="add")`, `InterfacePatch(name, type="", nets={})`, `DesignPatch(parts=[], nets=[], interfaces=[], remove_parts=[], remove_nets=[], disconnect=[])`; classmethod `DesignPatch.from_obj(patch: dict | str) -> DesignPatch`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_design_patch.py`:

```python
"""Phase C tests: declarative design patches (apply_design_patch + schema)."""

import pytest
from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit, nets, project_io
from skidl_mcp.tools.design_patch import (
    DesignPatch,
    NetPatch,
    PartPatch,
    PatchError,
    apply_design_patch,
    validate_patch,
)


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


class TestSchema:
    def test_from_dict_builds_typed_patch(self):
        p = DesignPatch.from_obj({
            "parts": [{"ref": "R1", "lib": "Device", "name": "R", "value": "10k",
                       "role": "pullup", "fields": {"Tol": "1%"}}],
            "nets": [{"name": "SDA", "role": "i2c_data", "pins": ["U1.SDA", "R1.1"],
                      "pins_mode": "set"}],
            "interfaces": [{"name": "i2c0", "type": "i2c", "nets": {"sda": "SDA"}}],
            "remove_parts": ["R9"],
            "remove_nets": ["OLD"],
            "disconnect": ["R2.2"],
        })
        assert isinstance(p.parts[0], PartPatch)
        assert p.parts[0].ref == "R1" and p.parts[0].value == "10k"
        assert p.parts[0].fields == {"Tol": "1%"}
        assert isinstance(p.nets[0], NetPatch)
        assert p.nets[0].pins == ["U1.SDA", "R1.1"] and p.nets[0].pins_mode == "set"
        assert p.interfaces[0].nets == {"sda": "SDA"}
        assert p.remove_parts == ["R9"] and p.disconnect == ["R2.2"]

    def test_from_yaml_string(self):
        p = DesignPatch.from_obj(
            "parts:\n  - ref: R1\n    lib: Device\n    name: R\n"
            "nets:\n  - name: GND\n    pins: [R1.2]\n"
        )
        assert p.parts[0].ref == "R1"
        assert p.nets[0].name == "GND" and p.nets[0].pins == ["R1.2"]

    def test_empty_patch_is_valid_and_empty(self):
        p = DesignPatch.from_obj({})
        assert p.parts == [] and p.nets == [] and p.remove_parts == []
        p2 = DesignPatch.from_obj(None)
        assert p2.parts == []

    def test_defaults_applied(self):
        p = DesignPatch.from_obj({"nets": [{"name": "N1"}]})
        assert p.nets[0].pins == [] and p.nets[0].pins_mode == "add" and p.nets[0].role == ""

    def test_non_mapping_raises_patch_error(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj([1, 2, 3])

    def test_bad_yaml_raises_patch_error(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj("parts: [unclosed")

    def test_part_without_ref_raises(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj({"parts": [{"lib": "Device", "name": "R"}]})

    def test_bad_pins_mode_raises(self):
        with pytest.raises(PatchError):
            DesignPatch.from_obj({"nets": [{"name": "N", "pins_mode": "wipe"}]})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_design_patch.py::TestSchema -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skidl_mcp.tools.design_patch'`.

- [ ] **Step 3: Write the schema implementation**

Create `src/skidl_mcp/tools/design_patch.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_design_patch.py::TestSchema -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/skidl_mcp/tools/design_patch.py tests/test_design_patch.py
git commit -m "feat(phase-c): design patch schema + dict/YAML parser"
```

---

## Task 2: Validation pass

**Files:**
- Modify: `src/skidl_mcp/tools/design_patch.py`
- Test: `tests/test_design_patch.py`

**Interfaces:**
- Consumes: `nets._find_pins(part, pin_id, ref) -> list | dict`; `CircuitEntry.parts` / `.nets` dicts.
- Produces: `validate_patch(entry, patch: DesignPatch) -> list[str]` — a list of actionable error strings (empty when the patch is applicable). Also private `_split_token(token) -> (ref, pin)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_design_patch.py`:

```python
def _two_resistors():
    """Active circuit with bare R1, R2 (pins 1 & 2). Offline-safe."""
    circuit.create_circuit("c")
    entry = manager.get_active()
    for ref in ("R1", "R2"):
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit, ref=ref)
        entry.parts[ref] = p
    return entry


class TestValidate:
    def test_valid_patch_has_no_errors(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]})
        assert validate_patch(entry, patch) == []

    def test_bad_pin_token_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R1.99"]}]})
        errors = validate_patch(entry, patch)
        assert errors and "R1.99" in errors[0]

    def test_unknown_part_ref_in_net_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"nets": [{"name": "N", "pins": ["R7.1"]}]})
        errors = validate_patch(entry, patch)
        assert errors and "R7" in errors[0]

    def test_net_may_reference_pin_on_part_created_by_same_patch(self):
        entry = _two_resistors()
        # U1 is being created in this patch; its pins can't be checked offline, so
        # the token is accepted at validation time (checked at apply).
        patch = DesignPatch.from_obj({
            "parts": [{"ref": "U1", "lib": "Device", "name": "R"}],
            "nets": [{"name": "N", "pins": ["U1.1"]}],
        })
        assert validate_patch(entry, patch) == []

    def test_new_part_without_lib_or_name_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"parts": [{"ref": "U1", "lib": "Device"}]})
        errors = validate_patch(entry, patch)
        assert errors and "U1" in errors[0]

    def test_remove_missing_part_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"remove_parts": ["R9"]})
        errors = validate_patch(entry, patch)
        assert errors and "R9" in errors[0]

    def test_disconnect_unknown_ref_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj({"disconnect": ["R9.1"]})
        errors = validate_patch(entry, patch)
        assert errors and "R9" in errors[0]

    def test_interface_referencing_unknown_net_reports_error(self):
        entry = _two_resistors()
        patch = DesignPatch.from_obj(
            {"interfaces": [{"name": "i2c0", "nets": {"sda": "NOPE"}}]})
        errors = validate_patch(entry, patch)
        assert errors and "NOPE" in errors[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_design_patch.py::TestValidate -q`
Expected: FAIL — `ImportError: cannot import name 'validate_patch'`.

- [ ] **Step 3: Write the validation implementation**

Add to `src/skidl_mcp/tools/design_patch.py` (imports at top, functions at end):

```python
from skidl_mcp.tools.nets import _find_pins
```

```python
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
                    errors.append(found["message"])
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_design_patch.py::TestValidate -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/skidl_mcp/tools/design_patch.py tests/test_design_patch.py
git commit -m "feat(phase-c): whole-patch validation pass"
```

---

## Task 3: Core applier — merge, atomicity, diff, dry_run

**Files:**
- Modify: `src/skidl_mcp/tools/design_patch.py`
- Test: `tests/test_design_patch.py`

**Interfaces:**
- Consumes: `manager.get_active()`; `project_io.serialize_entry(entry)`, `project_io.restore_entry(data, circuit=...)`; `skidl.Circuit`, `skidl.Net`; `validate_patch`; `_find_pins`; `_split_token`.
- Produces: `apply_design_patch(patch: dict | str, dry_run: bool = False) -> dict`; private `_empty_diff() -> dict`, `_apply(entry, patch, diff, warnings) -> None`, `_rollback(entry, snapshot) -> None`, exception `_ApplyError`. This task implements the additive path (create/update parts, create/update nets + connect, roles, interfaces); **removals are added in Task 4** (leave the `remove_*`/`disconnect`/`pins_mode` handling as documented no-op stubs the Task 4 tests will drive).

Diff shape (every key always present):
```python
{"parts_added": [], "parts_updated": [], "parts_removed": [],
 "nets_created": [], "nets_removed": [],
 "connections_added": 0, "connections_removed": 0,
 "roles_set": [], "interfaces_set": []}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_design_patch.py`:

```python
class TestApplyMerge:
    def test_low_level_and_patch_produce_identical_structure(self):
        # Circuit A: wire with low-level tools.
        circuit.create_circuit("a")
        a = manager.get_active()
        for ref in ("R1", "R2"):
            p = Part(name="R", tool=SKIDL,
                     pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                     circuit=a.circuit, ref=ref)
            a.parts[ref] = p
        nets.create_net("SDA")
        nets.connect("SDA", "R1", "1")
        nets.connect("SDA", "R2", "1")
        a.parts["R1"].value = "10k"
        data_a = project_io.serialize_entry(a)

        # Circuit B: identical bare parts, one patch does the rest.
        manager.reset()
        circuit.create_circuit("b")
        b = manager.get_active()
        for ref in ("R1", "R2"):
            p = Part(name="R", tool=SKIDL,
                     pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                     circuit=b.circuit, ref=ref)
            b.parts[ref] = p
        res = apply_design_patch({
            "parts": [{"ref": "R1", "value": "10k"}],
            "nets": [{"name": "SDA", "pins": ["R1.1", "R2.1"]}],
        })
        assert res["status"] == "ok"
        data_b = project_io.serialize_entry(b)
        # Structure identical apart from the circuit name.
        data_a["name"] = data_b["name"] = "x"
        assert data_a == data_b

    def test_diff_reports_what_changed(self):
        _two_resistors()
        res = apply_design_patch({
            "parts": [{"ref": "R1", "value": "1k", "role": "sense"}],
            "nets": [{"name": "N", "role": "signal", "pins": ["R1.1", "R2.1"]}],
            "interfaces": [{"name": "if0", "type": "sig", "nets": {"a": "N"}}],
        })
        assert res["status"] == "ok"
        ap = res["applied"]
        assert ap["nets_created"] == ["N"]
        assert ap["connections_added"] == 2
        assert "R1" in ap["parts_updated"]
        assert "part:R1" in ap["roles_set"] and "net:N" in ap["roles_set"]
        assert ap["interfaces_set"] == ["if0"]

    def test_roles_and_interfaces_stored_on_entry(self):
        entry = _two_resistors()
        apply_design_patch({
            "nets": [{"name": "N", "role": "signal", "pins": ["R1.1"]}],
            "parts": [{"ref": "R1", "role": "sense"}],
            "interfaces": [{"name": "if0", "type": "sig", "nets": {"a": "N"}}],
        })
        assert entry.roles["part:R1"] == "sense"
        assert entry.roles["net:N"] == "signal"
        assert entry.interfaces["if0"] == {"type": "sig", "nets": {"a": "N"}}

    def test_idempotent_reapply_is_empty_diff(self):
        _two_resistors()
        patch = {"parts": [{"ref": "R1", "value": "1k"}],
                 "nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]}
        first = apply_design_patch(patch)
        assert first["applied"]["connections_added"] == 2
        second = apply_design_patch(patch)
        assert second["status"] == "ok"
        ap = second["applied"]
        assert ap["parts_updated"] == [] and ap["nets_created"] == []
        assert ap["connections_added"] == 0 and ap["roles_set"] == []

    def test_validation_error_mutates_nothing(self):
        entry = _two_resistors()
        before = project_io.serialize_entry(entry)
        res = apply_design_patch({"nets": [{"name": "N", "pins": ["R1.99"]}]})
        assert res["status"] == "error" and res["errors"]
        after = project_io.serialize_entry(entry)
        assert before == after  # atomic: nothing changed

    def test_dry_run_reports_diff_without_mutating(self):
        entry = _two_resistors()
        before = project_io.serialize_entry(entry)
        res = apply_design_patch(
            {"nets": [{"name": "N", "pins": ["R1.1", "R2.1"]}]}, dry_run=True)
        assert res["status"] == "ok" and res.get("dry_run") is True
        assert res["applied"]["connections_added"] == 2
        after = project_io.serialize_entry(entry)
        assert before == after  # nothing actually changed

    def test_mid_apply_throw_rolls_back(self, monkeypatch):
        entry = _two_resistors()
        entry.parts["R1"].value = "10k"
        before = project_io.serialize_entry(entry)
        import skidl_mcp.tools.design_patch as dp

        # Force the connect step to explode after validation passes.
        def boom(*a, **k):
            raise RuntimeError("injected failure")
        monkeypatch.setattr(dp, "_connect_net_pins", boom)

        res = apply_design_patch({"nets": [{"name": "N", "pins": ["R1.1"]}]})
        assert res["status"] == "error" and res.get("rolled_back") is True
        after = project_io.serialize_entry(entry)
        assert before == after  # snapshot restored
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_design_patch.py::TestApplyMerge -q`
Expected: FAIL — `ImportError: cannot import name 'apply_design_patch'`.

- [ ] **Step 3: Write the applier implementation**

Add to `src/skidl_mcp/tools/design_patch.py`:

```python
from skidl import KICAD, Circuit, Net, Part

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import project_io
```

```python
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
        except _ApplyError as e:
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
    """Restore the active circuit to ``snapshot`` (taken before mutation)."""
    restored = restore_entry(snapshot, circuit=Circuit())
    # serialize_entry drops these non-structural fields; carry them across.
    restored.created_at = entry.created_at
    restored.requirements = entry.requirements
    restored.metadata = dict(entry.metadata)
    restored.project_root = entry.project_root
    manager.install(restored, activate=True)


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
```

Also add these **stubs** now (Task 4 fills them in and drives them with tests):

```python
def _apply_remove_parts(entry, patch: DesignPatch, diff: dict) -> None:
    ...  # implemented in Task 4


def _apply_remove_nets(entry, patch: DesignPatch, diff: dict) -> None:
    ...  # implemented in Task 4


def _apply_disconnect(entry, patch: DesignPatch, diff: dict) -> None:
    ...  # implemented in Task 4


def _prune_net_pins(net, entry, np: NetPatch) -> int:
    return 0  # implemented in Task 4
```

> **Note on the `serialize_entry`/`restore_entry` references:** they are used unqualified in `_rollback` (imported via `from skidl_mcp.tools.project_io import serialize_entry, restore_entry`) but qualified (`project_io.…`) in `apply_design_patch`'s dry-run branch. Import both names *and* the module so both forms resolve — add `from skidl_mcp.tools.project_io import restore_entry, serialize_entry` alongside the `from skidl_mcp.tools import project_io` import. Keep whichever single form you prefer; just be consistent when you type the code.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_design_patch.py::TestApplyMerge -q`
Expected: PASS (7 tests). The rollback test relies on `_connect_net_pins` being a module-level function so `monkeypatch.setattr` can replace it — keep it module-level.

- [ ] **Step 5: Run the whole suite for back-compat**

Run: `python -m pytest -q`
Expected: PASS — 127 baseline + new tests, nothing broken.

- [ ] **Step 6: Commit**

```bash
git add src/skidl_mcp/tools/design_patch.py tests/test_design_patch.py
git commit -m "feat(phase-c): atomic merge applier with diff, dry_run, rollback"
```

---

## Task 4: Removals — remove_parts, remove_nets, disconnect, pins_mode:set

**Files:**
- Modify: `src/skidl_mcp/tools/design_patch.py` (fill the four stubs)
- Test: `tests/test_design_patch.py`

**Interfaces:**
- Consumes: `pin.disconnect()` (SKiDL primitive used by `parts.remove_part`); `entry.circuit.rmv_parts(part)`; `_find_pins`; `_split_token`.
- Produces: fully implemented `_apply_remove_parts`, `_apply_remove_nets`, `_apply_disconnect`, `_prune_net_pins`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_design_patch.py`:

```python
class TestRemovals:
    def _wired(self):
        """R1.1-R2.1 on net N; R1.2 on net GND. Returns entry."""
        _two_resistors()
        apply_design_patch({
            "nets": [
                {"name": "N", "pins": ["R1.1", "R2.1"]},
                {"name": "GND", "pins": ["R1.2"]},
            ],
        })
        return manager.get_active()

    def test_remove_parts_detaches_and_deletes(self):
        entry = self._wired()
        res = apply_design_patch({"remove_parts": ["R2"]})
        assert res["status"] == "ok"
        assert res["applied"]["parts_removed"] == ["R2"]
        assert "R2" not in entry.parts
        # R1 untouched.
        assert "R1" in entry.parts

    def test_remove_nets_drops_net_and_disconnects_members(self):
        entry = self._wired()
        res = apply_design_patch({"remove_nets": ["N"]})
        assert res["status"] == "ok"
        assert res["applied"]["nets_removed"] == ["N"]
        assert "N" not in entry.nets
        # R1 pin 1 no longer connected; R1 pin 2 (GND) still is.
        assert not entry.parts["R1"].pins[0].is_connected()
        assert entry.parts["R1"].pins[1].is_connected()

    def test_disconnect_specific_pin_only(self):
        entry = self._wired()
        res = apply_design_patch({"disconnect": ["R1.1"]})
        assert res["status"] == "ok"
        assert res["applied"]["connections_removed"] == 1
        assert not entry.parts["R1"].pins[0].is_connected()
        # R2.1 (same net) is untouched.
        assert entry.parts["R2"].pins[0].is_connected()

    def test_pins_mode_set_prunes_unlisted_pins(self):
        entry = self._wired()  # N has R1.1 and R2.1
        res = apply_design_patch(
            {"nets": [{"name": "N", "pins": ["R1.1"], "pins_mode": "set"}]})
        assert res["status"] == "ok"
        assert res["applied"]["connections_removed"] == 1
        assert entry.parts["R1"].pins[0].is_connected()      # kept
        assert not entry.parts["R2"].pins[0].is_connected()  # pruned

    def test_pins_mode_add_keeps_existing(self):
        entry = self._wired()
        res = apply_design_patch(
            {"nets": [{"name": "N", "pins": ["R1.2"], "pins_mode": "add"}]})
        # add mode never prunes; R2.1 stays.
        assert res["applied"]["connections_removed"] == 0
        assert entry.parts["R2"].pins[0].is_connected()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_design_patch.py::TestRemovals -q`
Expected: FAIL — stubs do nothing, so assertions like `parts_removed == ["R2"]` fail.

- [ ] **Step 3: Implement the removal helpers**

Replace the four stubs in `src/skidl_mcp/tools/design_patch.py`:

```python
def _apply_remove_parts(entry, patch: DesignPatch, diff: dict) -> None:
    for ref in patch.remove_parts:
        part = entry.parts[ref]
        for pin in part.pins:
            pin.disconnect()
        entry.circuit.rmv_parts(part)
        del entry.parts[ref]
        diff["parts_removed"].append(ref)


def _apply_remove_nets(entry, patch: DesignPatch, diff: dict) -> None:
    for name in patch.remove_nets:
        net = entry.nets[name]
        for pin in list(net.pins):
            pin.disconnect()
        del entry.nets[name]
        diff["nets_removed"].append(name)


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_design_patch.py::TestRemovals -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the whole design-patch file + full suite**

Run: `python -m pytest tests/test_design_patch.py -q && python -m pytest -q`
Expected: PASS both.

- [ ] **Step 6: Commit**

```bash
git add src/skidl_mcp/tools/design_patch.py tests/test_design_patch.py
git commit -m "feat(phase-c): remove_parts/remove_nets/disconnect + pins_mode:set"
```

---

## Task 5: `inspect_design` filtered view

**Files:**
- Create: `src/skidl_mcp/tools/inspect.py`
- Test: `tests/test_inspect_design.py`

**Interfaces:**
- Consumes: `manager.get_active()`; `CircuitEntry.parts/.nets/.buses/.roles/.interfaces`; `validate.check_connections()`; `validate.run_erc()`.
- Produces: `inspect_design(by: str = "all", name: str = "", detail: str = "summary") -> dict`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_inspect_design.py`:

```python
"""Phase C tests: inspect_design filtered read-only view."""

import pytest
from skidl import SKIDL, Part, Pin

from skidl_mcp.circuit_manager import manager
from skidl_mcp.tools import circuit
from skidl_mcp.tools.design_patch import apply_design_patch
from skidl_mcp.tools.inspect import inspect_design


@pytest.fixture(autouse=True)
def clean_manager():
    manager.reset()
    yield
    manager.reset()


def _demo():
    circuit.create_circuit("demo")
    entry = manager.get_active()
    for ref in ("R1", "R2"):
        p = Part(name="R", tool=SKIDL,
                 pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
                 circuit=entry.circuit, ref=ref)
        entry.parts[ref] = p
    apply_design_patch({
        "parts": [{"ref": "R1", "role": "pullup"}],
        "nets": [{"name": "SDA", "role": "i2c_data", "pins": ["R1.1", "R2.1"]}],
        "interfaces": [{"name": "i2c0", "type": "i2c", "nets": {"sda": "SDA"}}],
    })
    return entry


class TestInspectDesign:
    def test_all_summary_has_counts_and_names(self):
        _demo()
        res = inspect_design(by="all", detail="summary")
        assert res["status"] == "ok"
        assert res["counts"] == {"parts": 2, "nets": 1, "buses": 0,
                                 "roles": 2, "interfaces": 1}
        assert set(res["parts"]) == {"R1", "R2"}
        assert res["nets"] == ["SDA"]

    def test_part_filter_by_name_full(self):
        _demo()
        res = inspect_design(by="part", name="R1", detail="full")
        assert res["status"] == "ok"
        assert res["part"]["ref"] == "R1"
        assert res["part"]["role"] == "pullup"
        assert any(p["number"] == "1" for p in res["part"]["pins"])

    def test_net_filter_lists_connections(self):
        _demo()
        res = inspect_design(by="net", name="SDA", detail="full")
        assert res["status"] == "ok"
        assert res["net"]["name"] == "SDA"
        assert res["net"]["role"] == "i2c_data"
        assert sorted(res["net"]["connections"]) == ["R1.1", "R2.1"]

    def test_role_filter(self):
        _demo()
        res = inspect_design(by="role")
        assert res["status"] == "ok"
        assert res["roles"]["part:R1"] == "pullup"
        assert res["roles"]["net:SDA"] == "i2c_data"

    def test_interface_filter(self):
        _demo()
        res = inspect_design(by="interface", name="i2c0")
        assert res["status"] == "ok"
        assert res["interface"]["nets"] == {"sda": "SDA"}

    def test_issues_surfaces_unconnected_pin(self):
        _demo()  # R1.2 and R2.2 are unconnected
        res = inspect_design(by="issues")
        assert res["status"] == "ok"
        assert res["unconnected_pins"] >= 2
        assert "R1" in res["parts_with_unconnected"]

    def test_unknown_by_reports_error(self):
        _demo()
        res = inspect_design(by="bogus")
        assert res["status"] == "error"

    def test_no_active_circuit_reports_error(self):
        res = inspect_design(by="all")
        assert res["status"] == "error"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_inspect_design.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skidl_mcp.tools.inspect'`.

- [ ] **Step 3: Write the implementation**

Create `src/skidl_mcp/tools/inspect.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_inspect_design.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/skidl_mcp/tools/inspect.py tests/test_inspect_design.py
git commit -m "feat(phase-c): inspect_design filtered read-only view"
```

---

## Task 6: Server wiring + docs (+ KiCad-gated creation test)

**Files:**
- Modify: `src/skidl_mcp/server.py` (import line 13; two new `@mcp.tool()` wrappers)
- Modify: `README.md` (document the two tools)
- Test: `tests/test_design_patch.py` (KiCad-gated creation equivalence)

**Interfaces:**
- Consumes: `design_patch.apply_design_patch`, `inspect.inspect_design`.
- Produces: MCP tools `apply_design_patch(patch, dry_run=False)` and `inspect_design(by="all", name="", detail="summary")`.

- [ ] **Step 1: Wire the tools into the server**

In `src/skidl_mcp/server.py`, change the tools import (line 13) from:

```python
from skidl_mcp.tools import circuit, parts, nets, generate, validate, project_io
```
to:
```python
from skidl_mcp.tools import (
    circuit, parts, nets, generate, validate, project_io, design_patch, inspect,
)
```

Add these two wrappers after the Project Persistence tools block (after `load_circuit`, before the Validation Tools section, around line 331):

```python
# ── Design Patch Tools (Phase C) ────────────────────────────────────────────

@mcp.tool()
def apply_design_patch(patch: dict | str, dry_run: bool = False) -> dict:
    """Apply a multi-part, multi-net design change in one structured patch.

    Merge semantics: parts/nets listed are created-or-updated and net pins are
    added. Destructive edits are explicit — ``remove_parts``, ``remove_nets``,
    ``disconnect: ["R1.2"]``, or a net's ``pins_mode: "set"`` (drops pins not
    listed). The whole patch is validated first (nothing changes on error) and is
    rolled back if a mutation fails, so it is atomic and safe to retry.

    Args:
        patch: a mapping or a YAML/JSON string with any of: parts, nets,
            interfaces, remove_parts, remove_nets, disconnect. Parts:
            ref/lib/name/value/footprint/role/fields. Nets: name/role/pins
            (``"R1.1"``/``"U1.SDA"``)/pins_mode. Interfaces: name/type/nets map.
        dry_run: validate and report the diff without changing the circuit.
    """
    return design_patch.apply_design_patch(patch, dry_run=dry_run)


@mcp.tool()
def inspect_design(by: str = "all", name: str = "", detail: str = "summary") -> dict:
    """Inspect the active design through a compact, filtered lens.

    Args:
        by: all | part | net | role | interface | issues.
        name: narrow to a single part/net/role/interface (ignored for all/issues).
        detail: summary (counts + names) | full (pins, connections, fields).
    """
    return inspect.inspect_design(by=by, name=name, detail=detail)
```

- [ ] **Step 2: Verify server imports cleanly** (only if FastMCP is installed; skip if not)

Run: `python -c "import skidl_mcp.server" 2>&1 | tail -1`
Expected: no output on success. If it prints `ModuleNotFoundError: No module named 'fastmcp'`, that is environmental — the tests below do not import the server; proceed.

- [ ] **Step 3: Add the KiCad-gated creation equivalence test**

Append to `tests/test_design_patch.py`:

```python
def _kicad_available() -> bool:
    try:
        from skidl import Part as _P
        _P("Device", "R", tool=__import__("skidl").KICAD, dest=__import__("skidl").TEMPLATE)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _kicad_available(), reason="needs KiCad symbol libraries")
class TestApplyCreatesPartsFromLibrary:
    def test_patch_creates_library_part(self):
        circuit.create_circuit("c")
        entry = manager.get_active()
        res = apply_design_patch({
            "parts": [{"ref": "R1", "lib": "Device", "name": "R", "value": "10k"}],
        })
        assert res["status"] == "ok"
        assert res["applied"]["parts_added"] == ["R1"]
        assert "R1" in entry.parts
        assert str(entry.parts["R1"].value) == "10k"
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. Offline, `TestApplyCreatesPartsFromLibrary` is skipped; everything else passes (127 baseline + all new tests).

- [ ] **Step 5: Document the tools in README.md**

Add a new table section after the "Project Persistence" section (after line ~195):

```markdown
### Design Patch (declarative editing)
| Tool | Description |
|------|-------------|
| `apply_design_patch` | Apply a multi-part / multi-net change in one structured, atomic patch (merge semantics; explicit `remove_parts`/`remove_nets`/`disconnect`/`pins_mode:set` for removals; `dry_run` to preview) |
| `inspect_design` | Compact, filtered read-only view: `by=all\|part\|net\|role\|interface\|issues`, `detail=summary\|full` |

`apply_design_patch` replaces a flurry of low-level calls with one declarative
edit. It validates the whole patch first (nothing changes on error) and rolls back
on any mid-apply failure, so it is atomic and safe to retry (re-applying a merge
patch is a no-op). The patch is a mapping or YAML string with any of `parts`,
`nets`, `interfaces`, `remove_parts`, `remove_nets`, `disconnect`.
```

Also add both tools to the tool count/overview if one is stated.

- [ ] **Step 6: Commit**

```bash
git add src/skidl_mcp/server.py tests/test_design_patch.py README.md
git commit -m "feat(phase-c): register apply_design_patch + inspect_design; docs"
```

---

## Self-Review

**1. Spec coverage:**
- Spec §3.1 `apply_design_patch(patch, dry_run)` → Tasks 1–4, 6. ✓
- Spec §3.2 / §8 `inspect_design(by, name, detail)` incl. `issues` → Task 5. ✓
- Spec §4 dataclass schema, dict-or-YAML → Task 1. ✓
- Spec §4.1 pin token grammar (`rpartition`, `_find_pins`, multi-match warning) → Task 2 `_split_token`, Task 3 `_connect_net_pins`. ✓
- Spec §5 merge + `remove_*`/`disconnect`/`pins_mode:set`; deterministic order; idempotency → Tasks 3–4 (`_apply` order; change-detected diff). ✓
- Spec §6 atomicity (validate-all; snapshot; restore on throw; rejected deepcopy/undo-stack) → Task 3 (`validate_patch` gate, `serialize_entry` snapshot, `_rollback`). ✓
- Spec §7 diff contract (all keys; error shape; `rolled_back`; `dry_run`) → Task 3 `_empty_diff` + return shapes. ✓
- Spec §9 module layout / role & interface storage keys (`part:<ref>`, `net:<name>`, `interfaces[name]`) → Tasks 1,3,5. ✓
- Spec §10 tests 1–6 → equivalence (T3), atomicity (T3), idempotency (T3), removals (T4), inspect filters (T5), back-compat (`python -m pytest -q` in T3/T4/T6). ✓
- Spec §11 acceptance (one-call sub-circuit, actionable errors + uncorrupted state, back-compat, same artifacts, idempotent) → covered; "same artifacts" is demonstrated by the byte-identical `serialize_entry` equivalence in T3 (structure drives every generator). ✓

**2. Placeholder scan:** The only `...` bodies are the Task 3 stubs, explicitly labeled "implemented in Task 4" and filled with real code there — intentional staging, not a placeholder gap. No "TBD"/"add error handling"/"write tests for the above" anywhere; every code step shows complete code.

**3. Type consistency:** `apply_design_patch(patch, dry_run=False)` and `inspect_design(by, name, detail)` signatures match across Tasks 3/5/6 and the server wrappers. `_connect_net_pins` is module-level in Task 3 and monkeypatched by that name in the Task 3 rollback test. Diff keys used in Task 3/4 tests (`parts_removed`, `nets_removed`, `connections_removed`, `roles_set`, `interfaces_set`) all exist in `_empty_diff`. Role keys `part:<ref>`/`net:<name>` and interface value shape `{"type":..., "nets":...}` are written in Task 3 and read in Task 5 identically.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-10-phase-c-design-patch.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
