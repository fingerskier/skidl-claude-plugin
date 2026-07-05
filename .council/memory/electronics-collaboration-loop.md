# Memory: Electronics Collaboration Loop

## Decision
The core product loop for this plugin is requirements -> encode design -> verify/validate -> loop, producing BOM and schematic models. Rendering and KiCad are downstream adapters, not proof of product value.
→ record: `records/20260705-153200-design-as-code-tool.md`

## Why
The user clarified that this plugin's primary concern is user+AI collaboration specific to electronics. The durable value is traceable electronic intent, encoded design state, validation evidence, and consistent BOM/schematic outputs, not whether a downstream renderer or KiCad adapter succeeds.

## Practice
Treat KiCad, SVG/PDF rendering, and other exports as adapter smoke tests. They should consume the canonical model and report adapter-specific failures without redefining whether the core design loop is valid.
