# KiClaw product direction — Hybrid Live

## Principle (non-negotiable)

> Deliver a strong **live feeling** using a hybrid architecture, without depending on deep unofficial GUI automation.

KiCad does not provide full, stable remote control of every editor and toolbar. We **design around** that limit.

## Target user experience

1. User opens a terminal and runs one command (`kiclaw workbench` / `kiclaw start`).
2. KiClaw starts the session, opens chat (or MCP serve), launches KiCad with the project.
3. Windows are arranged side-by-side when the OS allows.
4. User prompts in natural language (AI) or uses `kiclaw chat`.
5. The agent edits safely (file-first) and tries best-effort visual update.
6. The agent narrates what changed and **where to look**.

Success sounds like:

> “I ran one command, KiCad appeared next to the agent, I described what I wanted, and I watched the design update safely while the agent explained what it was doing.”

## Hybrid live architecture

| Layer | Role | Reliability |
|-------|------|-------------|
| **A. File-backed edits** | Snapshot → atomic write → hash guard → transaction → DRC/ERC | High |
| **B. Visual update** | IPC reload/refresh if possible; else clear reload guidance; optional screenshot | Medium–High |
| **C. Best-effort IPC** | Move/select when API Server + board open; instant file fallback | Medium |
| **D. Session / windows** | Launch KiCad, session state, side-by-side layout, `live_status` | High |

## Post-edit visual update order

1. Prefer official IPC refresh/reload of the open document.
2. Else instruct (or attempt) a simple reload path.
3. Optional: capture KiCad window screenshot for agent panel.
4. Always return structured diff + look-at guidance.

## Agent rules

1. Prefer safe file path for non-trivial changes.
2. Use IPC live actions only when stable and available.
3. After every mutation: confirm, summarize, say where to look, offer restore.
4. Be honest when something cannot be shown live.
5. Never claim full GUI mouse control.

## Explicitly accepted

- Not every action will be instant IPC.
- Some updates arrive via file reload.
- Product is “responsive + trustworthy”, not “full GUI puppet”.

## Priority

1. Perfect `workbench` / `start_engineering_session`
2. Reliable post-edit visual update
3. Expand stable IPC where it already works
4. Agent narration quality
5. Deeper analysis + safe edits
6. Heavier GUI automation only if official IPC improves
