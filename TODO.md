# TODO

## Done
1) [DONE] every claude run created skidl.* files — artifacts no longer created
   unless actually using the plugin. Fixed via `skidl_quiet` (removes skidl's
   import-time log handlers) + `do_backup=False` on netlist gen; guarded by
   `tests/test_no_artifacts.py`. (commit 48f65bb)

2) [DONE] moved the _how to_ content out of PLAN.md into HOWTO.md; README links
   both. PLAN.md now holds only the roadmap. (commit 90d2209)

3) [DONE] thorough repo review written up as a prioritized upgrade roadmap in
   PLAN.md. (commit facd9a6)

## Next (recommended, from PLAN.md — NOT yet implemented)
The review found the plugin's core loop is silently broken on a real machine.
These are the *fixes*, not the plan; awaiting go-ahead:
- P0.1 `parts.py:38` `dest=KICAD` → `tool=KICAD` (parts never join the circuit today)
- P0.2 `validate.py` ERC capture (run_erc always reports passed=True)
- P0.3 `str(part.lib)` → `part.lib.filename` (circuit_manager.py:38, generate.py:141,279)
- P0.4 wire discovered KiCad lib paths into skidl at startup (+ KiCad 10)
- P0.5 multi-pin connect (nets.py:55-59, 242-248)
- P0.6 real-KiCad integration test tier (would have caught all of the above)

See PLAN.md for the full P0–P3 roadmap.
