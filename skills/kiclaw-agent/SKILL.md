---
name: kiclaw-agent
description: Safely inspect, edit, verify, repair, and review KiCad projects through KiClaw MCP tools and CLI. Use for KiCad schematic or PCB changes, manufacturing checks, native ERC/DRC validation, reversible agent workflows, and evidence-backed project reviews.
---

# KiClaw engineering loop

Use KiClaw as a guarded engineering workflow, not as an unverified text editor.

## Operating modes

| Mode | When | Tools |
|------|------|--------|
| **Inspect** | First look / unknown project | `capability_report`, `compatibility_report`, `open_project`, `get_board_status`, `run_analysis` |
| **Analyze** | Design review without edits | `run_analysis`, `run_dfm`/`run_emc`/`run_si`/`run_thermal`, `review_project` |
| **Edit** | Guarded mutations only after inspect | snapshot → narrow mutator → native verify |
| **Release** | Manufacturing package | review pass + exports; keep transaction evidence |
| **Live** (optional future/limited) | Only when IPC session is real | `ipc_*` tools; never claim live success if unavailable |

Default to **Inspect → Analyze → (optional Edit) → Release**. Live mode is opt-in and never replaces snapshots/verification.

## Required loop

1. Call `capability_report` and `compatibility_report` first. Record KiCad version, CLI availability, IPC availability, concrete fixture checks, and limitations.
2. Call `open_project` or `project_info` and identify the exact board/schematic in scope.
3. Inspect before editing with `get_board_status`, `pcb_statistics`, `list_footprints`, `list_nets`, or `schematic_summary`.
4. Run `run_analysis` for deep structural packs (power tree, decoupling, protection, net clusters, ground strategy, connectivity gaps). Treat pack findings as triage with confidence labels — not lab certification.
5. Create a snapshot before every mutation. For file edits, retain the returned SHA-256 and pass it as `expected_sha256`.
6. Use the narrowest mutation tool. Call `pcb_backend_policy` or inspect `capability_report`; prefer IPC edits when a live board API reports the requested document is addressable, otherwise use guarded file tools. Never invent a successful IPC result when the session is unavailable.
7. After a mutation, inspect the structured diff and transaction ID. Confirm the intended count/property changed and no unrelated content changed.
8. Verify with `schematic_roundtrip_check`, native `run_erc`/`run_drc`, and `run_dfm` as applicable. Treat KiCad-native failures as blocking, even when lightweight parsing succeeds.
9. If verification fails, stop making new edits. Use the transaction snapshot to restore, re-inspect, and report the failure evidence.
10. For a completed project, run `review_project` (includes deep analysis) and return findings with severity, evidence, confidence, and source. Export only after review passes or the user explicitly accepts remaining findings.
11. When a component decision needs source evidence, call `datasheet_evidence` with an explicit local/HTTP artifact and explicit claims. Report the artifact hash and claim matches; never turn a URL or keyword hit into an unconditional design guarantee.

## Schematic rules

- Use `add_wire` for simple guarded wire insertion.
- Use `add_component` when cloning an existing library ID in the schematic.
- Use `add_custom_component` only when a project-local generated library is intended. Confirm that the returned library and `sym-lib-table` paths exist and that native ERC did not report a load failure.
- Do not claim arbitrary datasheet-derived symbol generation: the current custom tool clones a known-good definition and renames nested identities safely.

## PCB and manufacturing rules

- Treat lightweight board statistics as approximate.
- Use KiCad CLI DRC and exports as ground truth.
- Run `run_analysis` for structured power/ground/protection/decoupling/connectivity packs; do not invent regulator topologies or ESD ratings from names alone.
- Run `run_dfm` with explicit profile parameters when minimum trace width, fiducials, or test points matter.
- Run `run_emc` for conservative pre-compliance indicators; treat warnings as review prompts, not lab-equivalent certification.
- Call `spice_capability` before `run_spice`; if ngspice is unavailable, report that state instead of fabricating simulation results.
- Run `run_si` and `run_thermal` as triage indicators only; escalate to stackup-aware SI/PI and thermal simulation when they flag a design or when the requirement is safety-critical.
- Keep IPC and file backends session-pinned; refuse a write when the expected hash is stale.

## Product layout (split screen)

This is the experience we optimize for:

```text
┌─────────────────────────┬─────────────────────────┐
│  LEFT: Terminal / AI    │  RIGHT: KiCad GUI       │
│  kiclaw chat  OR        │  PCB / Schematic editor │
│  AI client + MCP serve  │  shows tool results     │
└─────────────────────────┴─────────────────────────┘
```

### How the user starts

```bash
# One command product entry
kiclaw start /path/to/project
# or create + open
kiclaw start --new MyBoard --dir ~/Documents

# Left terminal interactive commands
kiclaw chat

# Left terminal for full AI (Claude/Codex MCP)
kiclaw serve
```

Or from MCP: call `start_engineering_session` first, then execute the user's PCB request.

### Hybrid live model (official — see docs/PRODUCT.md)

We **do not** depend on deep unofficial GUI automation. We deliver a **live feeling** with:

1. **Primary:** safe file-backed edits (snapshot → atomic → verify).
2. **Visual update:** after each mutation call `refresh_kicad_view` and/or `narrate_mutation` so the user knows what to look at (IPC refresh if possible, else reload guidance).
3. **Best-effort IPC:** use `ipc_move_footprint` only when `live_status` is ready; fall back to file immediately on failure.
4. **Session:** `start_engineering_session` / `kiclaw workbench` launches KiCad, tries side-by-side layout, reports readiness.

#### After every mutation, respond like this

> I have [done X]. Snapshot created. Verification [passed/failed].  
> Please look at [area / component]. Visual path: [ipc_refresh | file_reload_guidance].  
> Would you like me to adjust anything or restore?

Never claim full mouse/toolbar control of KiCad.

## Reporting contract

Return: operation, target path, backend, transaction/snapshot IDs, before/after hashes, structured diff, native verification result, and unresolved findings. Distinguish `unavailable`, `verification failed`, and `design violation`; they require different next actions.
