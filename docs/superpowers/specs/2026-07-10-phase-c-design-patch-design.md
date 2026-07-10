# Phase C — Declarative Design Patch (`apply_design_patch` + `inspect_design`)

- **Status:** Approved design (brainstorming output), ready for implementation plan.
- **Date:** 2026-07-10
- **Issue:** [#7 "Revamp Phase C"](https://github.com/fingerskier/skidl-claude-plugin/issues/7) (phase of parent #4).
- **Depends on:** Phase B project persistence (`tools/project_io.py` serializer) — see `docs`/git history for `phase-b-project-persistence`.

## 1. Problem & Goal

Building a circuit today takes one MCP tool call per primitive edit (`add_part`,
`create_net`, `connect`, `connect_pins`, …). A modest sub-circuit — an I²C bus
with two pull-ups and a header — is a dozen round-trips of agent tool-call noise.

**Goal (verbatim from #7):** *"Reduce agent tool-call noise by allowing
multi-part, multi-net design changes in one structured patch."*

Deliver two new MCP tools while keeping every existing low-level tool working:

1. `apply_design_patch(patch, dry_run=False)` — apply a declarative, multi-entity
   change (parts, nets, connections, roles, interfaces, removals) in one call.
2. `inspect_design(by="all", name="", detail="summary")` — a filtered, compact,
   read-only view of the active circuit (not another full `get_circuit_info` dump).

## 2. Non-Goals (explicitly out of scope for this MVP)

- **No global `replace` mode.** Issue #7 floated `mode='merge'|'replace'`; we drop
  `replace` (a small patch silently wiping the board is a footgun and breaks
  idempotency against partial designs). Removals are always explicit and named.
- **Multi-unit symbol pins** (`U1A.OUT`) — deferred; a `REF.pin` token addresses a
  single-unit part only.
- **New tools from #7's v2 list** (`search_library`, `run_review`,
  `export_artifacts`, `run_world_scenario`) — those are renames / later phases.
- **Undo-stack transactional rollback** — the snapshot approach (§6) is sufficient.

## 3. Tool Surface

Two new `@mcp.tool()` wrappers in `server.py`, delegating to new modules. All 14
existing tools are unchanged and remain the low-level API `apply_design_patch`
composes.

### 3.1 `apply_design_patch(patch, dry_run=False)`
- `patch`: a JSON object **or** a YAML string (agents paste YAML readily). Parsed
  by `DesignPatch.from_obj`.
- `dry_run`: when `True`, run validation and compute the diff but mutate nothing —
  lets an agent preview the effect.
- Returns the **diff contract** (§7).

### 3.2 `inspect_design(by="all", name="", detail="summary")`
See §8.

## 4. Patch Schema

Modeled with **stdlib `dataclasses`**, not Pydantic — neither `pydantic` nor
`fastmcp` is importable in the test interpreter (only `yaml` is), and tests import
these modules directly. `DesignPatch.from_obj(obj)` accepts a dict or a YAML string,
validates key/type shape, and raises `PatchError` with an actionable message on
malformed input.

```yaml
parts:                       # create-or-update (merge)
  - ref: R1                  # required
    lib: Device              # required only when CREATING a new part (needs KiCad)
    name: R                  # required only when creating
    value: 10k               # optional; set/overwrite on existing
    footprint: Resistor_SMD:R_0805_2012Metric   # optional
    role: pullup             # optional  -> entry.roles["part:R1"]
    fields: {Tolerance: "1%"}                    # optional custom fields
nets:                        # create-or-update (merge)
  - name: SDA                # required
    role: i2c_data           # optional  -> entry.roles["net:SDA"]
    pins: [U1.SDA, R1.1]     # "REF.pin"; pin = number or name
    pins_mode: add           # add (default) | set (disconnect pins not listed)
interfaces:                  # create-or-update
  - name: i2c0               # required
    type: i2c                # optional label
    nets: {scl: SCL, sda: SDA}   # logical->net map -> entry.interfaces["i2c0"]
remove_parts: [R9]           # disconnect all pins, rmv from circuit
remove_nets: [OLD_BUS]       # disconnect all member pins, drop the net
disconnect: [R2.2]           # detach specific pins from whatever net they're on
```

Every top-level key is optional; an empty patch is valid and is a no-op.

### 4.1 Pin token grammar
A pin token is `REF.pin`, split on the **last** dot (`rpartition('.')`) — consistent
with Phase B's `_pin_token_key`. `REF` is a part reference designator; `pin` is a
pin **number or name**, resolved by reusing `nets._find_pins(part, pin, ref)`
(exact number or name match). Multi-match (a name shared by several pins) connects
**all** matches and emits a `warnings` entry, same behavior as the low-level
`connect`.

## 5. Merge & Removal Semantics

Default behavior is **merge**: entities listed under `parts`/`nets`/`interfaces`
are created if absent, updated in place if present; listed net `pins` are **added**.

Destructive edits happen **only** through named fields, never implicitly:
- `remove_parts: [...]` — reuse `parts.remove_part` logic (`pin.disconnect()` on
  every pin, `circuit.rmv_parts(part)`, drop from `entry.parts`).
- `remove_nets: [...]` — `pin.disconnect()` on every pin currently on the net, then
  delete `entry.nets[name]`.
- `disconnect: ["R1.2"]` — resolve via `_find_pins`, call `pin.disconnect()` on each
  matched pin.
- `pins_mode: 'set'` (per net) — after ensuring the listed pins are connected,
  `pin.disconnect()` any pin currently on the net that is **not** in the listed set.

All removals are grounded on `pin.disconnect()`, a real SKiDL primitive already
exercised by `parts.remove_part`.

**Idempotency:** re-applying an already-applied merge patch is a no-op that returns
an all-empty diff — agent retries are safe.

### 5.1 Deterministic apply order
1. `remove_parts`
2. `remove_nets`
3. `disconnect`
4. `parts` (create/update: value, footprint, fields, role)
5. `nets` (create/update; honor `pins_mode`; role)
6. `interfaces`

## 6. Atomicity (all-or-nothing)

Two-phase, snapshot-backed:

1. **Validation pass — no mutation.** Validate the *entire* patch against current
   indexes: the patch parses; every *new* part carries `lib`+`name`; every
   `REF.pin` token resolves (part exists and `_find_pins` yields ≥1 pin); every
   removal target exists; role/interface shapes are well-formed. **Any** failure
   returns `{"status":"error","errors":[...], "applied":<all-zero>}` and mutates
   nothing. Error strings mirror `find_part`'s `"…. Available: [ ... ]"` style.
2. **Snapshot + apply.** Take a snapshot with Phase B's
   `project_io.serialize_entry(entry)`, then apply mutations in the order above.
   If a mutation throws despite validation (defensive path), restore from the
   snapshot via `project_io.restore_entry` + `manager.install`, and return
   `{"status":"error","rolled_back":true, ...}`.

Rejected alternatives: `copy.deepcopy` of the Circuit (SKiDL Circuits hold pin/net/
lib back-refs and are not reliably deep-copyable — established in Phase B); a
per-op undo stack (correct but heavy for a path validation already makes
near-unreachable). Snapshot-restore reconstructs library-independent (bare) parts,
acceptable only on the rare defensive rollback.

## 7. Diff Contract

Success:
```json
{
  "status": "ok",
  "applied": {
    "parts_added": [], "parts_updated": [], "parts_removed": [],
    "nets_created": [], "nets_removed": [],
    "connections_added": 0, "connections_removed": 0,
    "roles_set": [], "interfaces_set": []
  },
  "warnings": []
}
```
Validation failure (nothing mutated):
```json
{ "status": "error", "errors": ["..."], "applied": { "...": [], "...": 0 } }
```
Defensive mid-apply failure additionally carries `"rolled_back": true`.
`dry_run=True` returns the `ok` shape with the computed diff, having mutated nothing.

## 8. `inspect_design`

A **filtered** read-only view, honoring Phase A's compact-output ethos — not a
re-dump of `get_circuit_info`.

- `by`: `all | part | net | role | interface | issues`.
- `name`: narrows to a single part / net / role / interface (ignored for `all` and
  `issues`).
- `detail`: `summary` (counts + names only) | `full` (pins, connections, fields,
  role/interface bindings).
- `by="issues"`: runs `validate.check_connections` + the last `run_erc` result and
  reports unconnected pins and ERC violations.

## 9. Module Layout

- **`src/skidl_mcp/tools/design_patch.py`** — dataclasses (`PartPatch`, `NetPatch`,
  `InterfacePatch`, `DesignPatch`), `PatchError`, `DesignPatch.from_obj`, and
  `apply_design_patch`.
- **`src/skidl_mcp/tools/inspect.py`** — `inspect_design`.
- **`src/skidl_mcp/server.py`** — two new `@mcp.tool()` wrappers; extend the tools
  import line.

Storage reuses Phase B fields on `CircuitEntry`: `roles` (keys `part:<ref>` /
`net:<name>`), `interfaces` (keyed by interface name).

## 10. Testing (red/green TDD)

1. **Equivalence** — build an I²C pull-up sub-circuit two ways (low-level tools vs a
   single patch); assert identical `summary()` / netlist.
2. **Atomicity** — a patch with one bad pin token: assert `serialize_entry` output
   is byte-identical before and after, and `status == "error"`.
3. **Idempotency** — apply a merge patch twice; the second returns an empty diff.
4. **Removals** — `remove_parts`, `disconnect`, and `pins_mode:'set'` each detach
   exactly the named targets and nothing else.
5. **inspect_design** — each `by` filter returns the correct shape; `by="issues"`
   surfaces a known unconnected pin.
6. **Back-compat** — the existing suite (127 tests) stays green.

## 11. Acceptance Criteria (from #7, refined)

- A multi-part, multi-net sub-circuit is created in **one** `apply_design_patch`
  call.
- Invalid patches return **actionable per-entity errors** and leave the circuit
  **uncorrupted** (validation pass; snapshot rollback on the defensive path).
- **Back-compatible:** all existing low-level tools and tests keep working.
- Patch-created circuits generate the **same** artifacts (netlist/BOM/SVG) as the
  equivalent low-level construction.
- **Idempotent:** re-applying an applied merge patch is a no-op (empty diff).
```
