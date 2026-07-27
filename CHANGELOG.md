# Changelog

All notable KiClaw changes are recorded here. The project follows semantic versioning.

## Unreleased

### Added

- **Deep Analysis Layer** (`run_analysis` / `kiclaw analyze`): deterministic packs for power-tree inventory, decoupling proximity, connector protection audit, net-name clusters, ground strategy, and PCB pad connectivity gaps — with evidence, confidence, and explicit triage disclaimers.
- Deep analysis is included in `review_board` / `review_project` under `checks.analysis`.
- MCP tool `run_analysis` and progressive-disclosure verify-category registration.
- Agent skill modes (Inspect / Analyze / Edit / Release / Live) and Live Visual Mode current-vs-future boundary.
- PyPI metadata for direct `pip install kiclaw` distribution.
- Companion npm launcher for `npx -y kiclaw serve` and Node-based MCP client configuration.
- Stderr-only MCP progress logs with tool names, success/failure state, and elapsed time.

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
