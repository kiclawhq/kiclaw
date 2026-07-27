# KiClaw product roadmap

## Product outcome

User connects an AI client (Claude/Codex/Cursor) to **KiClaw MCP + skills**.  
The agent can inspect, analyze, edit, verify, export, and (when Live is available) drive the **running KiCad GUI** so changes are visible on screen.

```text
AI client  --stdio MCP-->  kiclaw serve  -->  core (file-first) + optional IPC (live)
                              |
                              +--> skills/kiclaw-agent (engineering loop)
                              +--> kicad-cli (DRC/ERC/exports)
                              +--> kipy IPC (live PCB when API Server is on)
```

## Policies

1. **One feature = one commit** (or a small stack of related commits). Never dump unrelated work.
2. **Safety first**: snapshots, SHA-256 guards, atomic writes, native verify.
3. **Honest capabilities**: unavailable live tools return structured `ok: false`, never fake success.
4. **File-first default**; Live is opt-in upgrade.

## Phases

| Phase | Focus | Status |
|-------|--------|--------|
| 0 | Foundation MCP + guarded edits + review | Done (v0.1) |
| 1 | Deep analysis layer | Done (local; commit `feat: deep analysis`) |
| 2 | Rich inspection + project structure | In progress |
| 3 | Manufacturing BOM/CPL/release package | In progress |
| 4 | Expanded guarded schematic/PCB edits | Next |
| 5 | Library search/import | Next |
| 6 | Live Visual Mode (observability → limited live edits → continuous) | Scaffold → expand |
| 7 | Full matrix polish + CI matrix | Ongoing |

## Feature matrix (target)

See user brief categories 1–11. Each tool is tracked as:

- **exists** — shipped and tested
- **partial** — available with limitations
- **planned** — not implemented
- **live-gated** — implemented but requires KiCad API Server + optional `ipc` extra

## Live path (realistic)

| Step | What user sees |
|------|----------------|
| 1 | `kiclaw serve` + MCP client configured |
| 2 | Agent calls `capability_report` / `launch_kicad` |
| 3 | If IPC available: live probes + guarded `ipc_*` edits (unsaved, undoable) |
| 4 | Else: file-first path still works; agent reports live unavailable |

True “click Start → full live canvas control” needs KiCad GUI running with API Server enabled; KiCad 10 does not provide a headless API server.
