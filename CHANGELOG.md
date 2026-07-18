# Changelog

All notable KiClaw changes are recorded here. The project follows semantic versioning.

## [0.1.0] - 2026-07-18

### Added

- File-first MCP server with tools, `kicad://capabilities` resource, manufacturing-review prompt, and progressive tool discovery.
- KiCad CLI discovery, native DRC/ERC, Gerber, drill, SVG, and IPC-2581 exports.
- Approximate PCB inspection, schematic structural checks, byte-preserving round-trip validation, and guarded PCB/schematic mutations.
- Atomic replacement, snapshots, stale-hash rejection, transaction manifests, structured diffs, rollback, and backend session pinning.
- Optional KiCad IPC session probes and one-step live footprint movement through `kicad-python`.
- Deterministic DFM, EMC, SI/PI, thermal, SPICE capability, datasheet-evidence, compatibility, board review, and project review reports.
- CLI JSON review artifacts and GitHub Actions CI.
- Portable `skills/kiclaw-agent` inspect/edit/verify/report procedure.

### Compatibility

- KiCad 10.0.4 was detected and exercised on the development host.
- MCP is pinned to 1.27.2; HTTPX and Pydantic Settings are constrained to compatible, predictable import lines for this host.

### Known boundaries

- No product KiCad design is bundled with the repository, so manufacturing sign-off remains project-specific.
- Heuristic EMC, SI/PI, and thermal findings are triage indicators, not lab or simulation certification.
- Full schematic authoring, arbitrary symbol generation, datasheet inference, and multi-version KiCad qualification remain future work.
