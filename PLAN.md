# Dev / Test Plan

A guide for setting up, running, and verifying `skidl-claude-plugin` locally.
It captures the environment quirks discovered while hardening the plugin and
lists exactly what has been verified automatically vs. what still needs a
manual check against a real KiCad installation.

Verified against: **skidl 2.2.3**, **fastmcp 3.4.2**, Python 3.11, default
SKiDL tool `kicad9`.

---

## 1. Quick start

```bash
# from the repo root
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # see §2 if this fails to build
pytest                       # 68 tests
```

If the editable install fails while building `kinet2pcb` / `hierplace`,
use the workaround in §2 — the test suite itself does **not** need those
two packages.

---

## 2. Dependency build gotcha (important)

SKiDL pulls in two transitive dependencies — **`kinet2pcb`** and
**`hierplace`** — that ship legacy `setup.py` files which fail to build a
wheel on modern setuptools (≥ 80) with:

```
AttributeError: install_layout
```

These are PCB-placement helpers used only by SKiDL's board-layout features,
which this plugin does not call. Two ways to work around it:

**Option A — install SKiDL's import-time deps only (fast, used in CI):**

```bash
pip install skidl --no-deps
# then add the pure-Python modules SKiDL imports at runtime:
pip install graphviz simp_sexp
pip install pytest pytest-asyncio          # for the test suite
python -c "import skidl; print(skidl.__version__)"   # should import cleanly
```

Run the tests without installing the package (src layout):

```bash
PYTHONPATH=src pytest -q
```

This is enough to exercise everything except `generate_svg` (needs
`netlistsvg`, see §5) and `generate_kicad_schematic` against real symbols.

**Option B — pin a compatible setuptools and build normally:**

```bash
pip install "setuptools<80" wheel
pip install --no-build-isolation -e ".[dev]"
```

> Note: `server.py` imports `fastmcp`; the **tests do not** (they import only
> `skidl_mcp.tools.*` and `skidl_mcp.circuit_manager`). So you can run the
> suite without `fastmcp` installed. Install `fastmcp>=3.0.0` only when you
> want to launch the actual MCP server (`skidl-mcp`).

---

## 3. Running the server

```bash
skidl-mcp                    # stdio MCP server (needs fastmcp installed)
```

Register with Claude Code:

```bash
claude mcp add skidl -- uvx --from git+https://github.com/fingerskier/skidl-claude-plugin skidl-mcp
```

---

## 4. Test layout

| File | Covers |
|------|--------|
| `tests/test_circuit_manager.py` | `CircuitManager` lifecycle (create/switch/delete/find) |
| `tests/test_tools.py` | All tool functions: circuit, nets, parts, generate, validate, prompts |
| `TestExternalToolGracefulFailure` | Regression guard: missing libraries and the experimental SVG/schematic generators return `{"status":"error"}` and never raise |

Run a subset:

```bash
PYTHONPATH=src pytest tests/test_tools.py::TestExternalToolGracefulFailure -v
```

`prompts.py` has no SKiDL import, so prompt logic can be tested in isolation:

```bash
PYTHONPATH=src python -c "from skidl_mcp.prompts import get_prompt; print(get_prompt('design_voltage_divider', v_in='12', v_out='3.3', current_ma=''))"
```

---

## 5. Manual smoke test (end-to-end, no KiCad required)

The following exercises the core flow using SKiDL's generic `SKIDL` tool
backend (no KiCad libraries needed). `generate_netlist`, `generate_bom`,
and `export_python` produce real output; `generate_svg` /
`generate_kicad_schematic` are expected to return a clean error unless the
external tools / real symbols in §6 are available.

```python
# PYTHONPATH=src python smoke.py
from skidl import SKIDL, Part, Pin
from skidl_mcp.tools import circuit, nets, generate, validate, parts
from skidl_mcp.circuit_manager import manager

manager.reset()
circuit.create_circuit("divider", "12V -> 3.3V")
entry = manager.get_active()

def add(name, fp=""):
    p = Part(name=name, tool=SKIDL,
             pins=[Pin(num=1, name="p1"), Pin(num=2, name="p2")],
             circuit=entry.circuit)
    if fp:
        p.footprint = fp
    entry.parts[p.ref] = p
    return p.ref

r1 = add("R", "Resistor_SMD:R_0805_2012Metric")
r2 = add("R", "Resistor_SMD:R_0805_2012Metric")
nets.create_net("VIN");  nets.connect("VIN", r1, "1")
nets.connect_pins(r1, "2", r2, "1", net_name="VOUT")
nets.create_net("GND");  nets.connect("GND", r2, "2")

print("netlist :", generate.generate_netlist()["status"])      # ok
print("bom     :", generate.generate_bom("csv")["status"])     # ok
print("python  :", generate.export_python()["status"])         # ok
print("connchk :", validate.check_connections()["status"])     # ok
print("svg     :", generate.generate_svg()["status"])          # error w/o netlistsvg
print("schem   :", generate.generate_kicad_schematic()["status"])  # error w/o real symbols
```

Expected: the first four print `ok`; the last two print `error` with a
message that names the missing dependency. Crucially, **none of them raise.**

---

## 6. What still needs a real KiCad environment

These paths can only be fully validated with KiCad symbol libraries present.
Set the env var so SKiDL can find them (KiCad 9 shown):

```bash
export KICAD9_SYMBOL_DIR=/usr/share/kicad/symbols     # adjust per OS / version
```

| Feature | How to verify | Notes |
|---------|---------------|-------|
| `add_part` | `add_part("Device", "R", value="10k", footprint="Resistor_SMD:R_0805_2012Metric")` → `status: added` | Needs symbol libs |
| `search_parts` | `search_parts("resistor")` → structured `results` list of `{library,name,description}` | Now uses SKiDL's `fmt`/`file` API instead of stdout scraping |
| `libraries://list` resource | Should enumerate `.kicad_sym` files under the symbol dir | Path discovery now includes `KICAD9_SYMBOL_DIR` and `…/9.0/…` |
| `generate_svg` | Install [`netlistsvg`](https://github.com/nturley/netlistsvg) (`npm i -g netlistsvg`) + graphviz, then build a circuit and call it | SKiDL writes `<basename>.svg`; the tool now reads back the correct file |
| `generate_kicad_schematic` | Build a circuit from **real** `add_part` parts (bare SKIDL parts lack `pin.orientation` and cannot be routed) and open the result in Eeschema | Experimental SKiDL feature; tool writes to a temp dir via `filepath`/`top_name` |

---

## 7. Status of the review items

| Item | Finding | Resolution |
|------|---------|------------|
| #13 `add_part` exceptions | A bad part within a valid library raised an **uncaught `AttributeError`**, crashing the call | Broadened the `Part()` boundary to `except Exception` with a helpful message; regression test added |
| #15 `search_parts` parsing | Scraped free-form stdout and filtered by whole-line substring | Switched to SKiDL's `search_parts(query, fmt=…, file=…)` structured output; returns `{library,name,description}` dicts (also fixes a README/code mismatch) |
| #17 `fastmcp>=3.0.0` | **Verified valid** — fastmcp 3.x exists (latest 3.4.2) | No change |
| #18 `from skidl import SKIDL` | **Verified present** in skidl 2.2.3 | No change; suite passes |
| #19 `generate_kicad_schematic` | `file_` was silently ignored; real API uses `filepath` (dir) + `top_name`. Also crashed uncaught | Rewrote to use `filepath`/`top_name`, read back the produced file, fail cleanly; regression test added |
| (new) `generate_svg` | SKiDL appends `.svg` to the basename, so the old code read back an **empty temp file and reported `ok`** | Pass an extension-less basename, read back `basename + ".svg"`, fail cleanly if absent; regression test added |

---

## 8. Known limitations / future work

- **SVG export** requires `netlistsvg` (Node) + graphviz on PATH.
- **Schematic export** is experimental in SKiDL and only works with parts from
  real KiCad symbol libraries; complex circuits may still fail routing.
- The full `pip install -e .` is blocked by `kinet2pcb`/`hierplace` on modern
  setuptools (see §2). Consider upstreaming fixes or vendoring narrower deps if
  a clean one-command install becomes a requirement.
- CI suggestion: run `PYTHONPATH=src pytest` with `skidl --no-deps + graphviz +
  simp_sexp` (Option A) to keep the pipeline green without the unbuildable
  layout helpers.
