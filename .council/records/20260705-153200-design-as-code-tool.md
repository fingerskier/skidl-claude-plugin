# Record — Electronics Design-As-Code Core Loop

The council concluded that the next milestone should center this plugin on user+AI electronics collaboration, not on downstream rendering or KiCad handoff. The useful core loop is requirements -> encoded design -> deterministic verification/validation -> repair loop, yielding a BOM model and schematic model.

- **Session:** 20260705-153200-design-as-code-tool
- **Mode:** meeting
- **Concluded:** 2026-07-05 16:32
- **Chair:** staff-engineer
- **Seats:** staff-engineer, electrical-engineer, security-engineer, qa-engineer, product-manager
- **Task:** what are the next steps for making this a truly useful user+ai electronic design-as-code tool

## Recommendation
Build the next milestone around a narrow canonical electronics project model and a transactional AI collaboration loop:

`requirements -> typed design operations -> encoded design IR -> deterministic validate -> repair loop -> BOM + schematic model`

Scope it to one golden fixture first: an LED/power-rail example where an unsafe direct LED connection fails validation, the AI proposes a typed resistor repair, `apply` commits it atomically, validation passes, and BOM/schematic artifacts stay consistent. KiCad/rendering should be adapter smoke tests only, not the source of truth or proof of product value.

## Reasoning trail
The user corrected the initial council framing: the golden loop is not "make KiCad output." It is requirements -> encode design -> verify/validate -> loop. Rendering and KiCad are separate tools downstream of the canonical design.

That makes persistence alone the wrong next unit of work. Persisting parts and nets without requirements, electrical intent, validation evidence, BOM meaning, and schematic semantics just freezes an incomplete graph. The core contract has to come first.

The practical next step is a V1 schema and API contract:

- structured requirements with IDs, constraints, assumptions, and acceptance checks
- design IR with parts, nets, rails, pin intent, no-connects, footprints/packages, and traceability
- typed `propose/apply/validate` operations, not freeform file edits
- deterministic validation reports with stable issue IDs and requirement links
- derived BOM and schematic models as core outputs
- KiCad/SVG/PDF/export adapters fed from the canonical model, never treated as source of truth

This keeps the coupling sane: requirements drive design, design drives validation, validated design drives BOM/schematic. Adapters can fail separately without invalidating the core design loop.

## Dissents (preserved)
- **electrical-engineer:** I would not accept a core IR that only stores parts, nets, and values with optional metadata. That is a software graph, not an electronics design artifact. The minimum viable core must know rails, pin intent, ratings, explicit unknowns, connector assumptions, footprints/packages, and datasheet-backed assumptions, or the AI will be forced to invent hardware facts during validation and BOM generation.
- **security-engineer:** I dissent from any design where `propose/apply/validate` means the AI proposes a text diff and the plugin applies it to files. That is not a security boundary. The apply layer must be structural, schema-checked, revision-bound, path-confined, and incapable of writing outside the canonical project model except through controlled exporters.
- **qa-engineer:** I dissent from any acceptance plan that validates only "a KiCad file opens" or "a rendered schematic looks plausible." That misses the actual correctness risks: bad electrical semantics, inconsistent BOM, non-atomic AI edits, and unverifiable repair loops. The minimum bar is deterministic contract tests over requirements, design IR, validation report, BOM model, schematic model, atomic apply behavior, and repair loops.
- **product-manager:** I dissent from any MVP definition where KiCad output, rendering, or visual polish is treated as success before the canonical artifacts and validator prove the collaboration loop. I also dissent from expanding the first release beyond a constrained circuit class. Broad electronics coverage is not value if the user cannot trust the loop.

## Follow-ups
- [ ] Define the V1 canonical project schema: requirements, design IR, validation report, BOM model, schematic model. (owner: staff-engineer)
- [ ] Define minimum electrical semantics for rails, pins, connectors, no-connects, footprints, ratings, and BOM completeness. (owner: electrical-engineer)
- [ ] Specify the structural operation API for `propose`, `apply`, and `validate`, including revision binding and atomic failure behavior. (owner: security-engineer)
- [ ] Write golden, hostile, and degraded acceptance fixtures before implementation. (owner: qa-engineer)
- [ ] Select the constrained MVP circuit and user-facing success metric. (owner: product-manager)
- [ ] Confirm MVP non-goals: PCB layout, KiCad-first generation, pretty rendering, broad datasheet ingestion, procurement optimization, freeform file patching. (owner: user)

→ memory updated: `memory/electronics-collaboration-loop.md`
→ memory updated: `memory/canonical-design-model.md`
→ memory updated: `memory/typed-design-operations.md`
→ memory updated: `memory/mvp-golden-fixture.md`
