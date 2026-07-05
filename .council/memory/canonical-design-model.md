# Memory: Canonical Design Model

## Decision
Define a canonical electronics project schema covering structured requirements, design IR, validation report, BOM model, and schematic model before treating persistence or adapters as meaningful.
→ record: `records/20260705-153200-design-as-code-tool.md`

## Why
Persisting parts and nets alone would freeze an incomplete graph. A useful electronics design artifact must preserve requirements, assumptions, rails, pin intent, interfaces, no-connects, electrical ratings, BOM semantics, schematic hierarchy, and validation evidence.

## Minimum Contents
- requirements with stable IDs, constraints, assumptions, interfaces, operating conditions, and acceptance checks
- design IR with parts, nets, rails, connectors, signal intent, no-connects, variants, footprints/packages, and traceability
- validation report with deterministic issue IDs, severities, locations, requirement links, and validator version
- BOM model with quantities, refdes, values, packages, ratings, tolerances, MPNs or alternates, and sourcing/TBD status
- schematic model with logical sheets/blocks, pin-level connectivity, explicit no-connects, named nets, annotations, and electrical notes

## Standing dissent (electrical-engineer)
A core IR that only stores parts, nets, and values with optional metadata is a software graph, not an electronics design artifact.
