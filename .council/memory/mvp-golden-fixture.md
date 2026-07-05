# Memory: MVP Golden Fixture

## Decision
The first useful milestone should be a constrained fixture proving the requirements -> typed design operations -> validation -> repair loop, with consistent BOM and schematic models; broad electronics coverage comes later.
→ record: `records/20260705-153200-design-as-code-tool.md`

## Why
The MVP needs to prove the collaboration loop rather than a renderer. A narrow LED/power-rail fixture can demonstrate structured requirements, typed operations, deterministic validation, an intentionally failed direct-LED design, typed resistor repair, and synchronized BOM/schematic outputs.

## Acceptance Shape
- golden pass-from-empty loop for a simple LED indicator requirement set
- fail-then-repair case where validation catches direct LED-to-rail overcurrent and accepts a rated resistor repair
- BOM/schematic consistency case preserving separate refdes while grouping purchasable parts
- hostile cases for raw text diffs, path traversal, schema abuse, and electrical contradictions
- degraded cases for missing sourcing data, stale validators, and adapter failures

## Standing dissent (qa-engineer)
Acceptance cannot be a KiCad file opening or a rendered schematic looking plausible; it must be deterministic contract tests over the canonical artifacts and validator behavior.

## Standing dissent (product-manager)
Do not expand the MVP into broad electronics, rendering polish, KiCad-first output, or higher-level blocks before the collaboration loop is trustworthy.
