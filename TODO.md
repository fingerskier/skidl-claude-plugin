# TODO

## Done
1) [DONE] every claude run created skidl.* files - artifacts no longer created
   unless actually using the plugin. Fixed via `skidl_quiet` (removes skidl's
   import-time log handlers) + `do_backup=False` on netlist gen; guarded by
   `tests/test_no_artifacts.py`. (commit 48f65bb)

2) [DONE] moved the _how to_ content out of PLAN.md into HOWTO.md; README links
   both. PLAN.md now holds only the roadmap. (commit 90d2209)

3) [DONE] thorough repo review written up as a prioritized upgrade roadmap in
   PLAN.md. (commit facd9a6)

4) [DONE] P0 reliability fixes from PLAN.md:
   - `add_part` now passes `tool=KICAD`, so real KiCad parts join the circuit.
   - `run_erc` captures SKiDL's `erc_logger` records and reports warnings/errors.
   - summaries, BOMs, and Python export use `part.lib.filename` instead of the
     full library catalog string.
   - KiCad 10/library discovery is fed into `skidl.lib_search_paths[KICAD]` at
     server startup, with a `kicad_diagnostics` tool.
   - pin-name connections now connect all matching pins and report the set.
   - `tests/test_integration_kicad.py` covers the real-symbol add/wire/ERC/export
     path when KiCad symbols are available.

## Next (recommended, from PLAN.md)
P0 is complete. Continue with the highest-value roadmap items:
- P3.1 + P3.2 README/package correctness fixes.
- P1.1 design-as-code save/load/import persistence.
- P1.2 file-based KiCad/kicad-buddy handoff.

See PLAN.md for the full P0-P3 roadmap.
