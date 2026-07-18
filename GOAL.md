# v0.1 delivery goal

## Outcome

Deliver a usable local KiCad MCP server that can reliably inspect a real project, make a small PCB edit with rollback, and verify the result using the installed KiCad CLI.

## Success criteria

1. The server starts via stdio and advertises tools, resources, and prompts through the official MCP Python SDK.
2. `capability_report` discovers KiCad 10.0.4 even when `kicad-cli` is not on `PATH`.
3. A real `.kicad_pcb` can be summarized, snapshotted, edited, restored, DRC-checked, and exported through KiCad's own CLI.
4. Mutations use atomic replacement, create a snapshot first, reject stale expected hashes, persist a transaction manifest, return a structured before/after diff, and never claim file-parser statistics are exact.
5. Automated tests cover capability detection, parsing, snapshot restore, stale-write rejection, guarded track insertion, review findings, and CLI integration when KiCad is present.

## Deliberate boundary

The first IPC slice includes optional session/active-board probes and a guarded live footprint move through `kicad-python`. The live move is only enabled when KiCad's API Server is actually reachable, is grouped into one native undo step, records a disk snapshot and manifest, and leaves saving explicit. Full schematic editing, routing, simulation, and sourcing remain outside this slice.

## v0.2 validation and manufacturing goal

Extend the trusted loop into a project-level engineering review: combine native DRC/ERC with conservative deterministic checks, emit evidence-labelled findings with confidence and source, expose a CI-friendly JSON report, and export IPC-2581 through KiCad's CLI. This milestone deliberately does not claim datasheet-backed, EMC, SPICE, or full schematic-write capabilities yet; those require separate adapters and regression suites.

## Schematic fidelity next step

The first schematic slice provides structural verification plus guarded `add_wire`, constrained `add_component`, and project-local `add_custom_component` mutations. `add_component` clones an existing symbol instance from `lib_symbols`, assigns fresh UUIDs, changes reference/value/placement, verifies the semantic count and round-trip, and runs ERC. `add_custom_component` clones a known-good definition, consistently renames nested symbol identities, writes a registered `.kicad_sym`/`sym-lib-table`, and rejects/rolls back if native KiCad cannot load the result. Arbitrary hand-authored geometry and datasheet-driven generation remain future work.

## DFM validation next step

The deterministic DFM rule pack now checks outline presence/closure, references and values, minimum trace width, via geometry, and optional fiducial/test-point requirements. Advanced DFM, SI/PI, EMC, and thermal analysis remain separate adapters.

CI/review integration now includes a JSON-artifact-capable `kiclaw review` command and a GitHub Actions workflow that runs the test suite and project review on pushes and pull requests.

The portable `skills/kiclaw-agent` package defines the inspect → snapshot → guarded edit → native verify → repair/report loop. The MCP surface also provides progressive-disclosure routing through `list_tool_categories`, `find_tool`, and `run_tool`.

PCB mutations now expose an `auto` backend policy: live IPC is preferred only when KiCad reports an addressable PCB Editor document; otherwise the guarded file/CLI path remains the explicit fallback. `pcb_backend_policy` makes that decision observable without mutating a board.

Evidence-backed review begins with `datasheet_evidence`: it records a local/HTTP artifact's source, content type, byte count, SHA-256, explicit claim matches, and confidence. It intentionally does not infer electrical limits from an unreviewed source.

`compatibility_report` now emits a host/version/backend matrix and can exercise native DRC/ERC on a supplied project. It labels detected capability separately from concrete fixture verification, forming the basis for a versioned compatibility dashboard.

The first EMC slice is now available as `run_emc`: conservative ground-return, ground-zone, power-decoupling, and connector-protection heuristics with explicit pre-compliance disclaimers. It is included in `review_board` and never blocks solely on heuristic warnings.

The SPICE slice provides `spice_capability` and `run_spice`; when ngspice is installed, KiClaw runs a supplied netlist in batch mode and captures its report, otherwise it returns an explicit unavailable result.

SI/PI and thermal slices now provide `run_si` and `run_thermal` conservative indicators. They surface high-speed nets, missing differential-pair evidence, long segments, power-zone gaps, and thermal-management hints while explicitly disclaiming impedance, ripple, eye-diagram, junction-temperature, and derating claims.
