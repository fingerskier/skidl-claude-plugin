# Memory: Typed Design Operations

## Decision
AI changes should flow through typed structural operations with atomic apply, revision binding, provenance, and schema validation. Freeform file diffs are out of scope for the trusted core.
→ record: `records/20260705-153200-design-as-code-tool.md`

## Why
The trusted boundary should be the plugin code and pinned validator rules, not AI-authored file edits or validation prose. Requirements, AI proposals, human edits, symbols, footprints, datasheets, BOM rows, schematic metadata, validation reports, and adapter output remain untrusted until parsed and checked.

## Constraints
- `apply` accepts schema-checked operations such as setting requirements, adding components, assigning parts, connecting pins to nets, and marking no-connects.
- Invalid operations fail atomically and leave prior design state unchanged.
- Validation reports are reproducible evidence derived from design IR and validator version, not authority authored by the AI.
- Project artifacts remain path-confined and adapter exporters are controlled boundaries.

## Standing dissent (security-engineer)
`propose/apply/validate` must not mean the AI proposes a text diff and the plugin applies it to files.
