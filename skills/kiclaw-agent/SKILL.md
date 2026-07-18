---
name: kiclaw-agent
description: Safely inspect, edit, verify, repair, and review KiCad projects through KiClaw MCP tools and CLI. Use for KiCad schematic or PCB changes, manufacturing checks, native ERC/DRC validation, reversible agent workflows, and evidence-backed project reviews.
---

# KiClaw engineering loop

Use KiClaw as a guarded engineering workflow, not as an unverified text editor.

## Required loop

1. Call `capability_report` and `compatibility_report` first. Record KiCad version, CLI availability, IPC availability, concrete fixture checks, and limitations.
2. Call `open_project` or `project_info` and identify the exact board/schematic in scope.
3. Inspect before editing with `get_board_status`, `pcb_statistics`, `list_footprints`, `list_nets`, or `schematic_summary`.
4. Create a snapshot before every mutation. For file edits, retain the returned SHA-256 and pass it as `expected_sha256`.
5. Use the narrowest mutation tool. Call `pcb_backend_policy` or inspect `capability_report`; prefer IPC edits when a live board API reports the requested document is addressable, otherwise use guarded file tools. Never invent a successful IPC result when the session is unavailable.
6. After a mutation, inspect the structured diff and transaction ID. Confirm the intended count/property changed and no unrelated content changed.
7. Verify with `schematic_roundtrip_check`, native `run_erc`/`run_drc`, and `run_dfm` as applicable. Treat KiCad-native failures as blocking, even when lightweight parsing succeeds.
8. If verification fails, stop making new edits. Use the transaction snapshot to restore, re-inspect, and report the failure evidence.
9. For a completed project, run `review_project` and return findings with severity, evidence, confidence, and source. Export only after review passes or the user explicitly accepts remaining findings.
10. When a component decision needs source evidence, call `datasheet_evidence` with an explicit local/HTTP artifact and explicit claims. Report the artifact hash and claim matches; never turn a URL or keyword hit into an unconditional design guarantee.

## Schematic rules

- Use `add_wire` for simple guarded wire insertion.
- Use `add_component` when cloning an existing library ID in the schematic.
- Use `add_custom_component` only when a project-local generated library is intended. Confirm that the returned library and `sym-lib-table` paths exist and that native ERC did not report a load failure.
- Do not claim arbitrary datasheet-derived symbol generation: the current custom tool clones a known-good definition and renames nested identities safely.

## PCB and manufacturing rules

- Treat lightweight board statistics as approximate.
- Use KiCad CLI DRC and exports as ground truth.
- Run `run_dfm` with explicit profile parameters when minimum trace width, fiducials, or test points matter.
- Run `run_emc` for conservative pre-compliance indicators; treat warnings as review prompts, not lab-equivalent certification.
- Call `spice_capability` before `run_spice`; if ngspice is unavailable, report that state instead of fabricating simulation results.
- Run `run_si` and `run_thermal` as triage indicators only; escalate to stackup-aware SI/PI and thermal simulation when they flag a design or when the requirement is safety-critical.
- Keep IPC and file backends session-pinned; refuse a write when the expected hash is stale.

## Reporting contract

Return: operation, target path, backend, transaction/snapshot IDs, before/after hashes, structured diff, native verification result, and unresolved findings. Distinguish `unavailable`, `verification failed`, and `design violation`; they require different next actions.
