# Example: voltage divider (file-based artifact workflow)

A minimal, KiCad-free walkthrough of the Phase A file-based workflow: build a
12V → 3.3V resistive divider and export its netlist, BOM, and SKiDL Python to disk.

```bash
python examples/voltage_divider/build_divider.py
```

This writes into `examples/voltage_divider/artifacts/`:

| File | Tool | Contents |
|------|------|----------|
| `voltage_divider.net` | `generate_netlist(output_path=…)` | KiCad-importable netlist |
| `voltage_divider_bom.csv` | `generate_bom(output_format="csv", output_path=…)` | Bill of materials |
| `voltage_divider.py` | `export_python(output_path=…)` | SKiDL script that recreates the circuit¹ |

¹ The exported `voltage_divider.py` re-instantiates the resistors from the SKiDL
`Device` library, so **re-running that script needs a KiCad install** — unlike this
walkthrough, which builds the same circuit from bare parts and runs KiCad-free. The
export is a faithful round-trip of the design, not a dependency-free program.

Because each generator is given an `output_path`, the tool responses are compact —
`{status, format, path, bytes, summary}` — and the full artifact stays on disk
instead of flooding the model's context. Drop `output_path` to get the content
inline instead (small artifacts only).

The `artifacts/` directory is git-ignored; the script recreates it on each run.
`test_example_voltage_divider.py` runs this example against a temp dir in CI.
