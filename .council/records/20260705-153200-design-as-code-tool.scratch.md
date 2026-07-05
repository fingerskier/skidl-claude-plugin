# Scratchpad — meeting

This is ephemeral, append-only working memory for the council meeting. It will be archived into records if the meeting is concluded.

- **Task:** what are the next steps for making this a truly useful user+ai electronic design-as-code tool
- **Session:** 20260705-153200-design-as-code-tool
- **Started:** 2026-07-05 15:32
- **Chair:** staff-engineer
- **Seats (all seats speak in a meeting):** staff-engineer, electrical-engineer, security-engineer, qa-engineer, product-manager

---

## Context — repo snapshot

- Project: `skidl-claude-plugin`, package `skidl-mcp` version `2026.6.8`.
- Purpose in README: MCP server for designing electronic schematics using SKiDL; README still overclaims "PCB layouts" in places even though the plugin primarily supports schematic capture, validation, netlist/BOM/SVG/`.kicad_sch` export for downstream layout.
- Current MCP surface: circuit management, KiCad part search/add/list/remove/info, net and bus creation/connection, netlist/SVG/BOM/KiCad schematic/Python export, ERC/connection/footprint validation, KiCad diagnostics, circuit/library resources, and 16 prompt templates.
- Current core state from `PLAN.md`: P0 reliability shipped. Real KiCad core loop works on this machine: add real parts, wire, run ERC, export KiCad netlist. Test suite has 86 tests.
- Biggest current gap: `CircuitManager` is in-memory only; designs evaporate across server restarts. `export_python` exists but no `save_circuit`/`load_circuit`/import round trip.
- Current immediate backlog in `TODO.md`: P3.1/P3.2 docs correctness and remove PCB-layout overclaim; P1.1 design-as-code persistence; P1.2 file-based KiCad/kicad-buddy handoff.
- Roadmap high-value P1 items: persistence save/load/import; file-based output paths for handoff; deterministic EE calculators; tool docstrings/server instructions as model-facing UI.
- Roadmap deeper items: reusable hierarchical blocks, mutation tools, SPICE simulation, design-review pack, part metadata/BOM enrichment, bounded ranked part search/cache warm.
- Known cross-cutting risks: `generate_svg` may race netlistsvg; generator tools return large content inline instead of file paths; README/HOWTO/version claims drift; installation can hit SKiDL transitive dependency build issues.
- Relevant adjacent memory: Wright MCP explored circuit-design resources/tools/prompts around projects/files/footprints; Edith memory defines a richer KiCad automation MCP surface with ERC/DRC/export/render/open-document style file workflows.
- Council setup note: this repo-local council includes an added `electrical-engineer` seat focused on circuit behavior, datasheets, SKiDL/KiCad semantics, ERC, footprints, BOM, layout constraints, manufacturability, and avoiding invented hardware facts.

## Round 1 — staff-engineer

The next step is to make the tool a durable project system, not just a clever SKiDL command surface. Right now the core loop works, but the source of truth lives in RAM. That fails exactly when a user needs iteration: restart the server, hand off to KiCad, ask the AI to revise yesterday's design, or compare revisions.

Priority order:

1. **Fix the contract honestly**
   Clean up README/tool descriptions so it claims schematic design and downstream KiCad handoff, not PCB layout. This prevents the AI from planning workflows the tool cannot execute.

2. **Add persistence as P1**
   Implement `save_circuit`, `load_circuit`, and import/round-trip behavior around `export_python` or a stable project format. Acceptance test: create circuit, save, restart/load, mutate, ERC/export, and get equivalent artifacts.

3. **Move heavy outputs to files**
   Netlists, SVGs, BOMs, KiCad schematics, and generated Python should return paths plus summaries, not big inline blobs. This becomes the handoff boundary to KiCad/kicad-buddy and keeps MCP responses usable.

4. **Add deterministic design helpers**
   Resistor dividers, LED current limiters, regulator capacitor checks, pullups, RC filters, power budget, connector pin audits. These should be boring calculators with cited assumptions, not AI improvisation.

5. **Make validation the center of the workflow**
   The useful loop is: propose -> instantiate real parts -> connect -> run ERC/footprint checks -> explain failures -> patch. Tool docs and prompts should steer the model into that loop every time.

6. **Then build higher-level design blocks**
   Only after persistence and validation are solid: reusable subcircuits, mutation tools, block libraries, design-review packs, and part-ranking/cache work.

Who acts next:

- **Product manager** should define the first end-to-end user story: likely "save, reload, revise, export KiCad project."
- **Electrical engineer** should define the minimum validation/calculator set that prevents plausible bad circuits.
- **QA engineer** should turn that into red/green tests across restart, export paths, and ERC failure repair.
- **Security engineer** should review file path handling before arbitrary save/load/export lands.

No dissent from me on the scratchpad direction. The fragile part is clear: without durable state and file handoff, the tool cannot become design-as-code; it remains an interactive demo with export buttons.

## Round 1 — electrical-engineer

Minor dissent: persistence is necessary, but it must not persist only topology. A saved circuit also needs electrical intent: voltage domains, power inputs, ground strategy, expected current, connector pinouts, explicit no-connects, footprints/packages, and datasheet assumptions. Otherwise reload gives us named nets and parts, not a design.

Next EE priorities:

1. Add a minimal "electrical contract" to each circuit: rails, nominal voltages, max current, environment assumptions, connector roles, and required protection.
2. Make ERC the first gate, but add domain checks ERC will not catch: unpowered ICs, missing decoupling, floating enables/resets, rail-voltage mismatches, LED/resistor power margins, pullup voltage domains, and connector ESD/reverse-polarity expectations.
3. Require real KiCad symbols plus footprints for "production-intent" parts. A BOM line without package, rating, tolerance, and source/library identity should be flagged as incomplete.
4. Build deterministic calculators around common failure points: LED current limiters, dividers with input leakage/loading, pullups, RC filters, regulator dissipation, capacitor derating, and rail power budget.
5. Create one canonical smoke design: connector power input, protection, regulator, MCU, decoupling, reset/pullups, LED, and programming header. The useful loop is create -> validate -> export -> reload -> mutate -> validate.
6. Keep layout claims downstream until net classes, footprints, mounting constraints, thermal notes, and keepout/clearance requirements are represented.

ERC passing is necessary evidence, not sufficient evidence. The tool becomes genuinely useful when it can say "this schematic is electrically underspecified here" before the AI invents missing hardware facts.

## Round 1 — security-engineer

Dissent: persistence and file-based handoff are the right next product step, but they become the main trust boundary. Do not implement `save_circuit` / `load_circuit` / `export_*` as "accept a path and serialize some data" without a security contract.

Must-fix before P1 lands:

1. **Path confinement for all file tools.**
   Concrete attack: an AI call passes `../../.ssh/config`, `C:\Users\...\AppData\...`, or a symlinked project path as an export target and overwrites or exposes local files. Every load/save/export should resolve to a configured project root, reject traversal and absolute paths by default, and return paths, not file contents.

2. **No Python execution for round-trip import.**
   Concrete attack: a saved "design-as-code" file contains `import os; ...` and `load_circuit` executes it to reconstruct SKiDL state. That turns a circuit file into arbitrary code execution through the MCP server. Use a structured project format as the source of truth. Generated Python can be an export artifact, not the trusted import format.

3. **Treat KiCad libraries, part metadata, and generated netlists as untrusted input.**
   Concrete attack: malicious symbol fields or part names inject into generated Python, shell commands, SVG/XML, BOM CSV, or downstream KiCad files. All emitters need format-specific escaping. CSV cells beginning with `=`, `+`, `-`, or `@` need spreadsheet-injection handling.

4. **External tool invocation must be argument-safe and bounded.**
   Concrete attack: a net name, title, output path, or library identifier is interpolated into a shell command for `netlistsvg`, KiCad CLI, or SKiDL helpers. Invoke subprocesses with argv arrays, not shell strings; set timeouts; cap output size; isolate temp dirs per circuit/export.

5. **MCP surface needs an authorization model appropriate for local damage.**
   Concrete attack: any connected model/tool client can mutate or export every circuit and write files wherever the server allows. At minimum, require explicit project root configuration, make destructive operations explicit, and distinguish read-only inspection tools from mutation/export tools.

Hardening, but important:

- Add audit-friendly operation logs: tool name, circuit id, resolved path, artifact type, and validation result.
- Make circuit IDs opaque and scoped to a project, not global names that collide across sessions.
- Put dependency and library provenance in saved projects: SKiDL version, KiCad symbol library identity, footprint library identity. This is supply-chain hygiene and reproducibility.
- Keep secrets out of artifacts. Don't persist absolute user paths, environment variables, API keys, or MCP config into generated design files.

Security acceptance criteria for the next milestone: a hostile circuit name, net name, part field, library entry, and export path cannot write outside the project root, execute code, inject shell/XML/CSV/Python, or return large local file contents through the MCP response.

## Round 1 — qa-engineer

Dissent: persistence should not be first unless it is defined by a testable round-trip contract. Saving a wrong or incomplete circuit reliably is worse than volatile state because the user will trust it later.

Next steps from QA's side:

1. Define a canonical end-to-end fixture before implementation:
   - power input, protection, regulator, MCU, decoupling, reset, LED, programming header
   - real KiCad symbols and footprints
   - intentional electrical metadata: rails, voltages, current limits, no-connects, assumptions

2. Make round-trip correctness measurable:
   - create design through MCP tools
   - save project
   - restart server
   - load project
   - mutate one part/net/field
   - run ERC
   - export netlist/BOM/SVG/Python/KiCad handoff
   - compare stable semantic artifacts, not fragile formatting

3. Add negative fixtures for user-visible failures:
   - empty project save/load
   - missing KiCad libraries
   - unknown part after reload
   - duplicate pin names
   - malformed project file
   - version-skewed project file
   - huge circuit with hundreds/thousands of nets
   - concurrent edits to the same design
   - interrupted save leaving a partial file

4. Treat security cases as normal QA, not a separate afterthought:
   - circuit name tries path traversal
   - part field contains CSV/XML/Python/KiCad injection payloads
   - export path points outside project root
   - imported file attempts execution
   - subprocess hangs or floods output

5. Build calculators with property-based and boundary tests:
   - zero/negative/blank values
   - units with prefixes
   - extreme resistor/capacitor values
   - loaded divider math
   - regulator thermal limits
   - LED current margins
   - pullup timing/domain mismatches

6. Add "honesty tests" for docs and tool schemas:
   - every advertised tool exists
   - every prompt references valid tools
   - examples execute or are explicitly marked illustrative
   - package claims match implemented behavior

The release gate I would want: one golden design proves the happy path, one hostile design proves the trust boundary, and one degraded-environment design proves useful failure messages. Until those pass, this is still an impressive SKiDL command surface, not yet a dependable electronic design-as-code system.

## Round 1 — product-manager

I agree with the center of gravity, but I want to tighten the product framing: the next milestone is not "persistence" or "calculators." It is **a trustworthy resumeable design loop for an AI and a human working on the same circuit**.

Target user: a software-leaning builder or EE using an AI agent to create a small board and hand it off to KiCad without losing intent, files, or confidence.

Success metric: **from a fresh session, the agent can create the canonical smoke design, save it, restart, reload it, modify it, validate it, and export KiCad artifacts with no lost electrical intent and no unsafe file behavior.**

My proposed next steps:

1. **Define the V1 user contract**
   - "Given a small circuit request, SKiDL MCP creates a durable project folder with editable source, metadata, validation results, and exportable KiCad artifacts."
   - Explicit non-goals for this milestone: autorouting, full schematic layout quality, large-library intelligence, arbitrary Python import, and advanced block synthesis.

2. **Lock one golden workflow before implementation**
   - Use the EE-proposed canonical smoke design: power input, protection, regulator, MCU, decoupling, reset/pullups, LED, programming header.
   - This becomes the product acceptance test, not just QA infrastructure.
   - If the golden workflow is not pleasant and reliable, nothing higher-level matters.

3. **Make the saved project carry intent, but keep the schema small**
   - Minimum useful intent: named rails, expected voltages, max/current notes, ground strategy, connector pin purpose, footprints, explicit no-connects, assumptions.
   - I would resist storing every possible EE annotation now. The bar is: can a user or agent resume safely and understand why the circuit is shaped this way?

4. **File output must be first-class**
   - Inline generation is not enough for real use.
   - The user needs a project directory with durable source, generated netlist/ERC/BOM artifacts, and a clear status summary.

5. **Validation should guide the loop**
   - Not "run ERC and dump text."
   - The tool should say: what passed, what failed, what is unknown, and what the next likely fix is.
   - The product value is not merely artifact generation; it is reducing blind trust in AI-created electronics.

6. **Security and QA are release gates, not later hardening**
   - I support security's dissent: persistence creates a trust boundary.
   - I support QA's dissent: persistence without round-trip proof is false confidence.
   - Golden design, hostile design, and degraded-environment design should gate the milestone.

7. **Then add deterministic calculators**
   - Only after the durable loop exists.
   - Start with calculations that directly improve the smoke design: LED resistor, regulator headroom/thermal sanity, pullup sizing, divider values, decoupling checklist.
   - Metric: fewer unresolved validation warnings and fewer hand edits needed to make the canonical design reviewable.

My dissent: I would not prioritize "higher-level blocks" until the durable project loop is proven. Blocks are attractive, but they multiply wrongness if the system cannot yet preserve, validate, and explain a small board reliably. The smallest valuable product is a circuit project an AI can resume and a human can inspect without guessing what happened.

## User input after Round 1

the "golden" loop is: requirements -> encode design -> verify/validate -> loop; rendering/Kicad are separate tools; the primary concern for this plugin is user+AI collaboration specific to electronics that yields a BOM & schematic(s)

## Round 2 — staff-engineer

The correction changes the center of gravity. The plugin should not be "SKiDL wrapper plus KiCad export." Its core should be an electronics collaboration loop with a durable design record:

`requirements -> encoded design -> validation evidence -> revision loop -> BOM + schematic model`

Rendering and KiCad handoff are adapters. Useful, but downstream.

**Revised Architecture**

The core artifact should be a project-local electronics design package:

- `requirements`: stable IDs, constraints, assumptions, interfaces, operating conditions, acceptance checks.
- `design IR`: parts, nets, rails, connectors, signal intent, no-connects, variants, block ownership, datasheet-backed assumptions.
- `validation report`: ERC, requirement coverage, deterministic EE calculations, BOM completeness, unresolved assumptions, warnings.
- `BOM model`: normalized components, quantities, MPN candidates, alternates, lifecycle/status fields, sourcing assumptions.
- `schematic model`: logical sheets/blocks/connectivity/annotations that can be rendered or exported, but is not itself tied to KiCad.

The AI-facing API should operate on those artifacts through explicit propose/apply/validate steps. The failure mode to avoid is letting the model "edit a circuit" without a traceable reason, then discovering later that the output no longer satisfies the requirement it was meant to solve.

**Sequencing**

1. Define the canonical project schema first. Not KiCad, not rendering. Requirements, design IR, validation report, BOM, schematic model. This is the contract everything else hangs from.
2. Add requirement traceability. Every meaningful component, net, rail, interface, and validation check should be able to point back to one or more requirement IDs or explicit assumptions.
3. Build deterministic validation before higher-level generation. Start with boring checks: missing values, unconnected pins, undefined rails, current/voltage budget mismatches, connector pinout conflicts, BOM incompleteness, uncovered requirements.
4. Make the AI loop transactional. The model proposes a design delta, explains requirement impact, runs validation, and leaves a reviewable diff plus evidence. Human and AI should be able to resume from the same state without relying on chat history.
5. Generate BOM and schematic model from the canonical design. These are core outputs. KiCad netlist, SVG/PDF render, or other handoff formats are adapter outputs from the schematic/design model.

**Dissent Preserved**

Electrical-engineer dissent stands: if the IR only captures topology, it is insufficient. It must preserve electrical intent: rails, operating ranges, connector semantics, no-connects, footprints/packages where relevant, and datasheet assumptions.

Security-engineer dissent stands but moves later in sequencing: import/export adapters are the larger trust boundary. Core project files still need path confinement and safe parsing, but KiCad/rendering risk should not distort the core model.

QA-engineer dissent strengthens: the golden test is no longer "export to KiCad." It is a round trip where requirements produce an encoded design, validation catches a deliberate defect, the design is revised, and the final BOM plus schematic model are reproducible.

My call: define the canonical electronics project schema and validation contract next. Everything else should plug into that.

## Round 2 — electrical-engineer

Minimum semantics must include electrical intent, not just graph connectivity.

1. **Requirements**
   Capture operating envelope: input/output voltages, current budgets, load assumptions, environment, safety constraints, connector expectations, and allowed tolerances. A "3.3 V rail" is incomplete unless source, max load, ripple/noise expectation, and downstream consumers are known.

2. **Components**
   Each component needs role, symbol identity, package/footprint, value, tolerance/rating, manufacturer/MPN where relevant, and datasheet/source assumption. Generic passives are acceptable only if voltage, power, tolerance, and package class are explicit enough for BOM and layout.

3. **Pins And Nets**
   Pins need electrical function/type: power input, power output, bidirectional signal, analog input, open drain, no-connect, shield/chassis, etc. Nets need names, voltage domain where applicable, expected direction, current class, and whether they are intentionally floating, tied, or protected.

4. **Power And Ground**
   Encode rails as first-class objects: nominal voltage, source, consumers, current budget, sequencing constraints, enable/control nets, and decoupling requirements. Grounds need intent too: digital ground, analog ground, chassis/shield, isolated return, or single shared return. Do not let all `GND` collapse silently if the design intent differs.

5. **Interfaces**
   Connectors must include pinout, mating assumptions, signal levels, power limits, orientation/keying if known, and protection expectations. External-facing nets should be marked so validation can ask about ESD, reverse polarity, overcurrent, pullups, termination, or isolation.

6. **Validation Contract**
   Validation should check both syntax and circuit plausibility: unpowered ICs, missing returns, rail voltage mismatches, over-rated loads, floating required pins, duplicate/conflicting drivers, missing decoupling, missing pullups/pulldowns where pin mode requires them, unspecified no-connects, and BOM fields too vague to manufacture.

7. **Schematic Model**
   The schematic model should preserve hierarchy, references, pin-level connectivity, explicit no-connects, named nets, component annotations, and electrical notes. KiCad export can be an adapter, but this model must already be meaningful before KiCad sees it.

8. **BOM Model**
   BOM needs enough to buy and assemble: quantity, refdes, value, footprint/package, ratings, tolerance, manufacturer/MPN or approved alternates, lifecycle/source status if known, and "TBD" fields surfaced as validation findings.

Dissent: I would not accept a core IR that only stores parts, nets, and values with optional metadata. That is a software graph, not an electronics design artifact. The minimum viable core must know rails, pin intent, ratings, explicit unknowns, and external-interface assumptions, or the AI will be forced to invent hardware facts during validation and BOM generation.

## Round 2 — security-engineer

Treat the trust boundary as: **only the plugin code and pinned validator rules are trusted**. Requirements, AI proposals, human edits, imported symbols/footprints, supplier data, datasheets, BOM rows, schematic metadata, validation reports, and adapter output are all untrusted until parsed and checked.

**Must-Fix**

1. **No freeform apply path**
   The AI must not write project files directly. `apply` should accept only typed structural operations against the canonical schema: add component, connect pin to net, set requirement, assign part, etc. Concrete attack: prompt-injected datasheet text tells the AI to add `../../.ssh/config` as an artifact path or overwrite adapter config; a freeform file writer obeys it.

2. **Closed schema with hostile input assumptions**
   Requirements/design IR/BOM/schematic models need strict schemas: no unknown executable fields, no embedded scripts, no arbitrary expressions, no plugin hooks from project data. Concrete attack: a "validation formula" field becomes `python: import os...`, or a BOM field contains spreadsheet formula injection like `=WEBSERVICE(...)`.

3. **Validation report is evidence, not authority**
   The report must be reproducible from the design IR and validator version. Do not let AI-authored validation text mark a design safe. Concrete attack: AI edits both the design and validation report, marking missing fuse/protection as passed.

4. **Transactional collaboration with provenance**
   Every AI or human change should have author, timestamp, base revision, operation list, and validation result. Use optimistic concurrency. Concrete attack: AI validates revision A, human changes a rail limit in revision B, stale "pass" remains attached and gets exported.

5. **Path confinement for all artifacts**
   Project artifact references must be relative logical IDs resolved inside the project root or artifact store. Reject absolute paths, parent traversal, symlinks crossing root, device paths, and adapter-controlled output paths. Concrete attack: malicious symbol library references `..\..\AppData\...` or causes KiCad/export adapters to overwrite local config.

6. **Adapter boundary stays narrow**
   KiCad/rendering adapters should consume canonical model only, not arbitrary project scripts or external libraries by default. Escape every string emitted into KiCad, SVG, HTML, CSV, Markdown, and JSON. Concrete attacks: net name breaks output syntax; component description injects HTML; BOM opened in Excel exfiltrates via formula.

7. **Secrets and proprietary data controls**
   If AI calls a remote model, the plugin must make it explicit what gets sent: requirements, part choices, design notes, possibly proprietary schematic intent. No silent upload of full project, local files, environment variables, tokens, or supplier credentials.

8. **Supply-chain controls for parts/libraries**
   Supplier metadata, symbols, footprints, datasheet-derived assumptions, and component libraries are untrusted dependencies. Record source URL, retrieval time, hash/version where possible, and distinguish "claimed rating" from "validated design assumption." Concrete attack: poisoned footprint swaps pin order or a fake part rating causes unsafe design.

**Hardening / Nice-to-Have**

- Stable opaque IDs for components/nets/requirements, with human labels treated as display text only.
- Character allowlists for reference designators, net names, pin IDs, package names, and file stems.
- Separate "design intent," "selected part," and "adapter realization" so unsafe adapter quirks do not mutate the canonical model.
- Local audit log that can reconstruct why a BOM or schematic changed.
- Optional signed/pinned validator packages if third-party validators become installable.

**Dissent**

I dissent from any design where `propose/apply/validate` means the AI proposes a text diff and the plugin applies it to files. That is not a security boundary. The apply layer must be structural, schema-checked, revision-bound, and incapable of writing outside the canonical project model except through controlled artifact exporters.

## Round 2 — qa-engineer

Smallest verifiable plan should prove the loop, not the renderer. Acceptance is on canonical artifacts and validator behavior.

**Core Contract**
Every test should assert:

- Requirements are structured, versioned, and traceable into design decisions.
- AI output is only typed proposed operations.
- `apply` is atomic: invalid operations leave prior design unchanged.
- `validate` is deterministic and returns stable issue IDs, severities, locations, and requirement links.
- BOM and schematic model are derived from the accepted design IR, not separately invented.
- KiCad/render output is adapter smoke only, never the source of truth.

**Golden Cases**

1. **Pass-from-empty loop**
   Scenario: requirements specify `5V input`, `LED indicator`, target current range, connector, ground, operating temperature.
   Expected: proposal creates connector, LED, resistor, named `+5V` and `GND` rails, net connections, BOM entries, schematic model symbols/pins/nets. Validator passes.

2. **Fail-then-repair loop**
   Scenario: initial proposal connects LED directly across `5V/GND`.
   Expected: validator rejects with overcurrent/current-limiting issue. Next typed operation inserts resistor with computed value/rating. Validator then passes. BOM and schematic model reflect only final accepted state.

3. **BOM/schematic consistency**
   Scenario: accepted design has two identical resistors and one unique LED.
   Expected: BOM groups identical purchasable parts correctly while schematic still has distinct references; every schematic component has a BOM mapping unless explicitly non-purchasable.

**Hostile Cases**

1. **Unsafe mutation attempt**
   Scenario: AI proposes raw text diff, file write, KiCad file patch, or path traversal.
   Expected: rejected before apply; project state unchanged; validation not treated as authority for unsafe input.

2. **Schema abuse**
   Scenario: unknown fields, null required fields, wrong enum values, huge strings, duplicate component IDs, duplicate net names with conflicting meaning.
   Expected: closed-schema rejection with actionable error; no partial apply.

3. **Electrical contradiction**
   Scenario: requirements say `3.3V-only MCU`, design connects pin to `5V`; or shorts `+5V` to `GND`.
   Expected: validator emits blocking electrical issues tied to exact component/pin/net and requirement.

**Degraded Cases**

1. **Missing optional sourcing data**
   Scenario: component has valid symbol/package/value but no MPN/datasheet.
   Expected: design may validate with warning; BOM marks sourcing incomplete. User-visible because purchasing cannot proceed.

2. **Validator unavailable or stale**
   Scenario: pinned validator cannot run or schema version mismatch.
   Expected: no pass claim. Output is "unverified," adapters/export disabled or clearly gated.

3. **Adapter failure**
   Scenario: canonical schematic/BOM validate, but KiCad export fails.
   Expected: core acceptance remains green; adapter reports separate failure. User-visible only as export unavailable, not design invalid.

**Dissent**

I dissent from any acceptance plan that validates only "a KiCad file opens" or "a rendered schematic looks plausible." That misses the actual correctness risks: bad electrical semantics, inconsistent BOM, non-atomic AI edits, and unverifiable repair loops. The minimum bar is deterministic contract tests over requirements, design IR, validation report, BOM model, and schematic model.

## Round 2 — product-manager

**Product Framing**

The product is not "AI draws circuits." The product is a trustworthy collaboration loop where a user states an electronics intent, the AI encodes it into a structured design, validation catches design mistakes, and the loop produces a coherent BOM and schematic model.

Primary user: someone using AI to move from requirements to an electrically reviewable design artifact without losing traceability or inventing hidden assumptions.

Core outcome: the user can tell what was requested, what was designed, what assumptions were made, what failed validation, and what changed to fix it.

**MVP Scope**

The MVP should prove one narrow, end-to-end golden path:

1. Capture simple requirements with operating envelope.
2. Encode them into canonical project artifacts: requirements, design IR, BOM model, schematic model.
3. Validate electrical consistency with reproducible findings.
4. Let AI propose typed structural repairs.
5. Apply repairs through controlled operations.
6. Re-validate and show BOM/schematic consistency.

The LED example is sufficient if it demonstrates the real loop: direct LED connection fails validation, resistor repair is proposed/applied, BOM updates, schematic model updates, validation passes.

Rendering and KiCad export are downstream adapter smoke tests only. They are not the MVP's proof of value.

**Explicit Non-Goals**

Not in MVP:

- PCB layout.
- KiCad-first project generation.
- Pretty rendering as primary output.
- Full SPICE/simulation coverage.
- General-purpose electronics design across arbitrary domains.
- Automatic datasheet ingestion at broad scale.
- Procurement/vendor optimization.
- Freeform AI patching of design files.
- Polished UI beyond what is needed to inspect the loop.

**Success Metric**

Primary metric: for the golden fixture set, the system produces a validated BOM and schematic model from requirements in no more than 3 propose/apply/validate iterations, with 100% detection of seeded critical electrical errors in that fixture set.

Secondary product signal: a user can inspect the final artifacts and answer: "what changed, why, and what evidence says it is valid?"

**Dissent**

I dissent from any MVP definition where KiCad output, rendering, or visual polish is treated as success before the canonical artifacts and validator prove the collaboration loop.

I also dissent from expanding the first release beyond a constrained circuit class. Broad electronics coverage is not value if the user cannot trust the loop.
