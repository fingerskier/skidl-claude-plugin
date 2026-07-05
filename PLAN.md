# Upgrade Roadmap — from "demo" to "engineer's daily +1"

This is the forward-looking plan for `skidl-claude-plugin`. Dev/test how-to
lives in [HOWTO.md](./HOWTO.md); user-facing docs live in [README.md](./README.md).

This roadmap starts after the P0 reliability release. The core loop now works on
this machine with real KiCad symbols: add real parts, wire them, run ERC, and
export a KiCad netlist. The next work should focus on making that fixed core more
persistent, file-oriented, documented, and comfortable for repeated real use.

Priority legend — effort: **S** ≤2h · **M** ½–1 day · **L** multi-day.
Impact is relative to "usable as a real EE's daily tool."

---

## Shipped — P0 reliability release (2026-07-05)

The P0 release fixed the real-KiCad core loop and added regression coverage:

- `add_part` now adds real KiCad symbols to the active circuit with assigned refs.
- `run_erc` captures SKiDL `erc_logger` records and reports warnings/errors.
- circuit summaries, BOMs, and Python export use compact library names instead
  of dumping full library catalogs into tool output.
- KiCad 10 and standard symbol paths are discovered at startup and appended to
  `skidl.lib_search_paths[KICAD]`; `kicad_diagnostics` reports path/cache state.
- `connect` and `connect_pins` connect every matching duplicate pin name.
- `tests/test_integration_kicad.py` covers real-symbol add/export/ERC/multi-pin
  behavior when KiCad symbols are available.

Verification at ship: `python -m pytest -q --basetemp .pytest-tmp -p no:cacheprovider`
passed with 86 tests.

---

## P1 — The "+1" leap (highest-value features)

### P1.1 — Design-as-code persistence: save / load / import · M · impact: high

Today `CircuitManager` is a pure in-memory dict; the MCP server restarts every
Claude Code session, so **every design evaporates**, and `export_python` is a
one-way export path with no `load` counterpart. This is
the single biggest demo-vs-daily-driver gap: a companion that forgets the design
between sessions can't carry a multi-day project. skidl's entire value
proposition is *circuits as git-diffable code* — lean into it.

**Approach:**
- `save_circuit(path)` — a corrected `export_python` (uses `lib.filename`,
  preserves pin names / footprint / fields, deterministic ordering for clean git
  diffs) that writes into the user's project.
- `load_circuit(path)` — `exec` the file inside `with entry.circuit:` (skidl
  `Circuit` is a context manager that sets `default_circuit`), then rebuild
  `entry.parts`/`entry.nets` from `entry.circuit`.
- `import_kicad_netlist(path)` — use skidl's `netlist_to_skidl` so existing KiCad
  designs can be onboarded.
- Optional autosave-on-mutation to `<project>/circuits/<name>.py`.
- Round-trip test: build → save → fresh manager → load → identical netlist.

### P1.2 — First-class kicad-buddy handoff (file-based, not inline text) · M · impact: high

This user runs the **kicad-buddy** plugin (`open_document`, `export_netlist`,
`run_drc`/`run_erc`, `render_pcb`, `export_gerbers`). Today the two don't compose:
skidl-mcp returns netlist/`.kicad_sch` **text inline**, kicad-buddy wants files on
disk. A documented, file-based division of labor turns two toys into one pipeline:
*describe circuit → skidl writes netlist/schematic files → kicad-buddy imports,
lays out, DRCs, renders, fabs.*

**Approach:**
- Add optional `output_path` to `generate_netlist`/`generate_kicad_schematic`/
  `generate_bom`; when given, write the file and return `{path, summary}` instead
  of the full content (this also fixes context flooding — see X.2).
- Ship a plugin skill/command (`pcb-handoff`) documenting the flow and clarifying
  that skidl ERC is connectivity-level while kicad-buddy ERC/DRC is authoritative.
- Evaluate `Circuit.generate_pcb` (via kinet2pcb) for direct `.kicad_pcb`, gated
  as optional (kinet2pcb's legacy `setup.py` breaks on setuptools ≥ 80, per
  HOWTO §2).

### P1.3 — Deterministic design calculators (E-series aware) · M · impact: high

The 16 design prompts tell Claude to "calculate R1 and R2" itself — LLM
arithmetic on component values is exactly where silent wrong-BOM errors come from.
An EE +1 must get the numbers right *every* time. Small, pure-Python, testable
calculators get used in nearly every session.

**Approach:** new `tools/calc.py` (no skidl dependency):
`calc_voltage_divider(vin, vout, i_ma, series='E24'|'E96')` → best standard pairs
with actual Vout + error %; `calc_led_resistor(vsupply, vf, i_ma)` with power-rating
check; `calc_rc_filter(fc, order)`; `calc_i2c_pullup(vbus, cap, speed)`;
`calc_555(mode, f_or_t)`; `calc_lc_match(f, z_src, z_load, topology)`. Each returns
chosen standard values + formula + margins. Update the matching prompt templates to
"call `calc_*` first, then add parts with the returned values." Unit-test against
known-good references.

### P1.4 — Docstrings & server instructions as the model-facing UI (single source of truth) · M · impact: high

Claude's effectiveness is bounded by what the tool descriptions say. Today the
24 `server.py` wrappers are trivial pass-throughs with docstrings that have
**drifted** from the richer `tools/*.py` versions, and both omit return contracts,
hard prerequisites (netlistsvg/graphviz for SVG; KiCad libs for search/add), the
experimental flag on `generate_kicad_schematic`, and — most important — the fact
that **all state is in-memory and lost on restart**. So Claude learns these facts
by failing in front of the user.

**Approach:**
- Eliminate the duplication: register the `tools/*.py` functions directly
  (`mcp.tool()(parts.add_part)` — verified working on fastmcp 3.4.2; names/schemas
  come from `__name__`/type hints and match today's, so clients see no change).
- **Gotcha (verified):** fastmcp 3.4.2 parses Google-style docstrings and
  **silently drops the `Returns:` section whenever an `Args:` section is present**.
  So return contracts, prerequisites, and workflow hints must go in the docstring
  **body before `Args:`**, never in a `Returns:` block. The existing `Returns:`
  sections are already invisible to the model.
- Keep enrichment to 1–3 lines per tool (24 tools × bloat lands in every session's
  context).
- Expand `server.py` `instructions` (currently surfaced verbatim to clients) with
  the state-lifecycle warning ("circuits live in memory for this session only;
  `save_circuit`/`generate_netlist` to persist") and the canonical flow
  *create → add → connect → run_erc → export*.
- Add a contract test that iterates registered tools via `await mcp.get_tool(name)`
  and asserts each description names its status/error contract, that
  `generate_svg` names `netlistsvg`, and that `generate_kicad_schematic` says
  "experimental". (This test imports `server.py`, so it needs `fastmcp` in the test
  env — run it in the project venv.)

---

## P2 — Depth (scales the tool to real designs)

### P2.1 — Hierarchical subcircuits / reusable blocks · L · impact: high

The flat 24-tool surface caps out around 15 parts before wiring calls become
unmanageable. skidl already ships `@subcircuit`, `Group`, `SubCircuit`, and
`Interface`. Build on P1.1: a `blocks/` directory of `@subcircuit`-decorated
functions (`ldo_rail`, `mcu_atmega328`, `usb_c_device_port`, `i2c_bus`,
`decoupling`) shipped with the plugin and user-extendable. Tools: `list_blocks`,
`describe_block`, `instantiate_block(name, params, net_bindings)` (exec inside
`with entry.circuit:` and bind the block's `Interface` nets to existing nets).
Migrate the best prompt templates into executable blocks so the LLM composes
*verified* building blocks instead of re-wiring from prose. Subsumes "more
templates."

### P2.2 — Mutation tools (iterate without teardown) · S · impact: medium

There is no `set_part_value`/`set_footprint`/`disconnect_pin`/`rename_net`. The
commonest review loop — "make R2 4.7k", "this footprint should be 0603" — can only
be done by `remove_part` (which disconnects every pin) + full rewire. skidl
supports in-place mutation trivially (`part.value = …`, `part.footprint = …`,
`pin.disconnect()`). Add these; they make iterative refinement cheap.

### P2.3 — SPICE simulation · L · impact: medium

Closing the loop from "wired correctly" (ERC) to "works electrically" (sim) is what
separates a design companion from a netlist typist. Verified feasible here (InSpice
1.7.0.1 + skidl's spice backend import on this Python). Constraint: SPICE circuits
must be built from pyspice-library parts with the SPICE tool, not KiCad symbols — so
map simulable parts (R/C/L/D, V/I sources, behavioral opamp) into a parallel SPICE
`Circuit`. `tools/simulate.py`: `simulate(analysis='op'|'tran'|'ac', spec)` → op-point
table / waveform CSV (written to project dir, not inline) + min/max/settling summary;
warn which parts weren't mapped. Start with `.op`/`.tran` on RLC+source subsets.

### P2.4 — Design-review pack · M · impact: medium

An EE's weekly ritual. skidl gives most of it nearly free (`Circuit.generate_dot`
+ the already-installed `graphviz` package). Tools: `generate_connectivity_graph`
(SVG to project dir), `net_report` (per-net fanout, single-pin nets, no-driver
nets, power nets missing decoupling), `power_budget` (per-rail current vs regulator
capability via `set_part_field` attributes). Fold into one `design_review` prompt
that runs ERC + connection/footprint checks + net report + graph.

### P2.5 — Part metadata & BOM enrichment · M · impact: medium

KiCad symbols carry `datasheet` and `keywords` (verified populated), but
`get_part_info`/`search_parts` throw them away. **Stage 1 (S):** include
`datasheet`/`keywords`/`description` in results; add `set_part_field(ref, name,
value)` for MPN/manufacturer/DNP and carry them into `generate_bom` columns and the
netlist — makes the BOM fab-house-ready. **Stage 2 (L, optional):** `quote_bom`
against Mouser/Digi-Key REST (keys via env), unit price at qty breaks + stock +
lifecycle, disk-cached, degrades gracefully with no keys.

### P2.6 — Part-search UX: bounded, ranked, cache-warm · S · impact: medium

`search_parts` can still flood (unbounded, unranked), and skidl's first search
builds its cache slowly (minutes over 200+
libraries) with no feedback, so it feels broken over MCP. Add `max_results`
(default ~40) + `truncated` flag + `offset` paging; rank exact-name → keyword →
description; include `pin_count`/`datasheet` per row. Pair with
`kicad_diagnostics` and an explicit cache-warm tool.

---

## P3 — Docs, packaging & hygiene

### P3.1 — README correctness fixes (ship immediately) · S · impact: high

Two concrete errors defeat a stranger today, independent of any restructure:
- **`README.md:57`** tells Claude *Desktop* users to edit
  `~/.claude/claude_desktop_config.json` — that's Claude *Code*'s directory.
  Real path is `%APPDATA%\Claude\claude_desktop_config.json` (Windows) /
  `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS); note
  `command` must be an absolute path or on PATH.
- The **Development** block (`README.md:135-138`) and the manual install
  (`README.md:33-35`) use `pip install -e .`, which hits the kinet2pcb/hierplace
  build failure (HOWTO §2). Add a one-line caveat linking HOWTO §2 (Option A/B).
  Do **not** collapse Option A into `pip install skidl --no-deps graphviz simp_sexp
  pytest` — that applies `--no-deps` to pytest and installs it broken; keep the
  three separate commands, and drop the bash-only `PYTHONPATH=src` prefix
  (redundant now that `pyproject.toml` sets `pythonpath=["src"]`).

### P3.2 — Drop the "PCB layouts" overclaim · S · impact: high

`plugin.json:4`, `README.md:3`, and `pyproject.toml:8` all say "schematics and PCB
layouts." There are no layout tools — the plugin does schematic capture,
validation, and netlist/BOM/SVG/`.kicad_sch` export *for* layout in pcbnew. For a
marketplace card and the README's first sentence, this promises a capability that
doesn't exist and costs credibility with exactly the daily-driver audience.
Rewrite all three to the accurate value prop; extend `plugin.json` keywords with
`circuit`, `netlist`, `bom`, `erc`, `hardware`, `circuit-design`.

### P3.3 — Capability matrix + worked example + troubleshooting (in README/HOWTO) · M · impact: high

- **Worked end-to-end example** in README: one real transcript for the voltage
  divider (prompt → `create_circuit → add_part ×2 → connect → run_erc →
  generate_netlist`), abridged tool responses, first ~15 netlist lines, the BOM
  CSV. Check in an `examples/` dir with 2–3 complete artifacts (divider, 555
  astable, ATmega328P breakout: `.py` + `.net` + `.csv` + rendered `.svg`) — these
  double as golden regression files. **Generate them by driving the fixed server**
  (post-P0), so the transcript is real, not aspirational.
- **Capability matrix**: columns for no-KiCad / KiCad / KiCad+netlistsvg so users
  know what works before installing.
- **Per-OS env + troubleshooting** in HOWTO: a table of
  OS × KiCad-version → symbols dir and `KICAD9_SYMBOL_DIR` (Windows `setx`, macOS
  app-bundle path, Linux `/usr/share/kicad/symbols`), a ready-to-paste `.mcp.json`
  `env` block, and an **error decoder** mapping the exact strings users see
  (`Can't open file`, `No active circuit`, skidl's `KICAD9_SYMBOL_DIR … missing`
  warning, the SVG missing-tool message) to fixes. Note env vars are read once at
  server start — after `setx`, fully restart Claude Code. Correct HOWTO §6/§7:
  `netlistsvg` needs **Node.js only** (`npm i -g netlistsvg`), *not* graphviz —
  skidl's `graphviz` is a pip package used only by the unexposed `generate_graph`.

### P3.4 — CHANGELOG / CI / CONTRIBUTING · M · impact: medium

Calver releases with user-visible changes and no changelog read as a demo. Add:
- **CHANGELOG.md** (Keep-a-Changelog, calver headings) backfilled from `git log`
  v2026.3.10 → HEAD; user-visible entries include the `search_parts` structured-output
  change and `generate_kicad_schematic` rewrite (both PR #3 / `407cfb9`), the
  un-openable-library skip (`ebf9b19`), and the working-dir artifact fix (`48f65bb`).
- **`.github/workflows/test.yml`** implementing HOWTO's recipe (skidl `--no-deps` +
  graphviz + simp_sexp, plain `pytest`) across Python 3.10–3.14 on ubuntu+windows,
  plus the `integration_kicad` real-symbol job; add a status badge.
- **CONTRIBUTING.md** pointing at HOWTO for the dev env and stating the red/green
  TDD expectation the repo already follows.

### P3.5 — Reliable `uvx` install + documented failure modes · M · impact: high

The zero-install promise (`README.md:29`, `uvx --from git+…`) is the front door,
and skidl's transitive deps (kinet2pcb/hierplace, confirmed in metadata) can fail
to build on setuptools ≥ 80 — a cryptic first-run failure with no user-facing
note. First **verify from a clean uv cache** whether the resolve actually breaks
(it may ship wheels; the documented failure was sdist builds on Debian-patched
distutils — it built fine on vanilla Windows here). If it breaks: publish
`skidl-mcp` wheels to PyPI (so `.mcp.json` becomes `uvx skidl-mcp` with a locked
resolution) and/or add `[tool.uv]` overrides pinning known-good versions. Either
way add a README "Installation troubleshooting" subsection: the kinet2pcb symptom
+ workaround, uvx cold-start latency (multi-minute first clone/resolve — can trip
MCP startup timeouts) + a pre-warm command, and how to confirm the server is alive
(`claude mcp list`).

### P3.6 — Template reference (auto-generated) · S · impact: medium

The 16 prompts are a headline feature but undiscoverable: README lists names and
stops — no argument reference, no note that these surface as slash commands, no
mention of the existing `list_design_templates` prompt. `prompts.py` already holds
the full argument schemas, so **hand-writing a reference guarantees drift**. Add a
small script (make target / pre-commit) that renders `prompts.py` into
`docs/templates.md` (name, description, argument table with required flags +
example values), plus a pytest asserting the file is current.

---

## Cross-cutting notes (fold into the work above)

- **X.1 — `generate_svg` has a fire-and-forget race.** skidl launches netlistsvg
  via `subprocess.Popen` with no wait; `generate.py:93-110` checks for the output
  file immediately and then `rmtree`s the temp dir — so the tool can report "no
  output file" even with netlistsvg installed, and deletes the dir under the
  still-running process. Add a bounded poll-for-file wait before advertising a
  reliable "SVG" capability column (P3.3).
- **X.2 — Generator outputs flood context.** `generate_netlist`/`generate_svg`/
  `generate_kicad_schematic`/`generate_bom` write a temp file, read it back,
  delete it, and return the **full content** inline (tens of KB for real designs).
  The EE's actual need is a file on disk their KiCad project / kicad-buddy can
  open. The `output_path` parameter in P1.2 fixes both the flooding and the
  round-trip.
- **X.3 — Verification/version drift.** HOWTO/README cite specific skidl/fastmcp
  versions while `pyproject.toml` only pins `skidl>=2.2.0` with no upper bound and
  no compatibility matrix. Add a single compatibility statement (skidl range,
  KiCad versions, Python range) rather than scattering it across files.

## Suggested sequencing

1. **P3.1 + P3.2** (10-minute correctness/credibility fixes).
2. **P1.1 (persistence)** → unlocks **P1.2 (kicad-buddy)** and **P2.1 (hierarchy)**.
3. **P1.3 (calculators)** and **P1.4 (docstrings)** in parallel — both are
   self-contained and high-leverage.
4. **P3.3–P3.6** docs/hygiene as the feature set stabilizes.
5. **P2.3 (SPICE)** and **P2.5 stage 2 (sourcing)** last — highest effort, most
   optional.
