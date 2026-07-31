# Changelog

All notable KiClaw changes are recorded here. The project follows semantic versioning.

## Unreleased

### Added

- **Hybrid live product direction** (`docs/PRODUCT.md`): file-first safety + best-effort visual update; no fake full GUI control.
- **Post-edit visual update**: `refresh_kicad_view`, `narrate_mutation`, `arrange_side_by_side` (macOS layout + IPC refresh attempt + reload guidance).
- **Workbench defaults**: `kiclaw workbench` opens chat by default and attempts side-by-side terminal/KiCad layout.
- **Split-screen product workbench**: `kiclaw start` / `kiclaw workbench` launches KiCad, sets session mode, and prints the terminal-left / KiCad-right guide; MCP tool `start_engineering_session`.
- **Interactive left-terminal REPL**: `kiclaw chat` for doctor/open/analyze/move/review without a cloud model; `start --then chat|serve` handoff.
- **Project session lifecycle**: `create_new_project`, `open_project_session`, `save_project`, `close_project`, `get_active_project`.
- **Library tools**: `search_symbols`, `search_footprints`, `get_symbol_info`, `get_footprint_info`, `list_*_libraries`, `create_project_library`, `import_symbol_to_project`, `import_footprint_to_project`.
- **Fuller edit surface**: `delete_track`, `delete_via`, `place_footprint`, `create_zone`, `fill_zones` (honest limit), `lock/unlock_footprint`, `delete_component`, `delete_wire`, `rotate_component`, `dry_run_edit`, `validate_design_rules`, `generate_assembly_notes`.
- **Live extras**: `ipc_save_board`, `ipc_place_footprint`/`ipc_add_track` (capability-honest when IPC incomplete).
- **Rich inspection tools**: `list_project_files`, `get_project_structure`, `list_components`, `get_component_details`, `get_footprint_details`, `get_net_details`, `get_layer_stack`, `get_design_rules`, `find_objects`, `get_drc_errors`, `get_erc_errors`, `check_connectivity`, `get_transaction_history`.
- **Manufacturing exports**: `export_bom`, `export_pos`/`export_cpl`, `export_netlist`, `export_pdf_schematic`, `create_release_package` (native kicad-cli).
- **Guarded edit expansions**: `add_via`, `rotate_footprint`, `delete_footprint`, `set_footprint_property`, `add_net_label`, `move_component`, `set_component_value`, `place_power_symbol`.
- **Deep analysis aliases**: `analyze_power_tree`, `analyze_decoupling`, `audit_protection`, `analyze_subcircuits`, `analyze_buses`, `analyze_passive_networks`.
- **Live scaffolding**: `launch_kicad`, `live_status`, `render_board`, plus honest live-gated stubs for selection/highlight/zoom/switch_editor.
- **Agent ops**: `get_agent_mode` / `set_agent_mode`, `require_approval`, `get_tool_help`, `suggest_next_actions`.
- Roadmap at `docs/ROADMAP.md` (commit-per-feature policy + product outcome).
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
