"""Product workbench: split-screen engineering session (terminal + KiCad).

Target experience:
  Left  — terminal: user prompts / interactive commands / MCP AI client
  Right — KiCad GUI: PCB/schematic editor reflecting agent tool actions

``kiclaw start`` launches KiCad, sets session state, prints the layout guide,
and can hand off to ``serve`` (MCP) or ``chat`` (local REPL).
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

from .agent_ops import set_agent_mode, suggest_next_actions
from .core import (
    board_summary,
    capability_report,
    move_footprint,
    project_info,
    review_project,
    run_analysis,
    run_check,
)
from .live import launch_kicad, live_status, open_in_kicad
from .project_session import (
    close_project,
    create_new_project,
    get_active_project,
    open_project_session,
    save_project,
)
from .visual_update import arrange_side_by_side, narrate_mutation, refresh_kicad_view


PRODUCT_BANNER = r"""
╔══════════════════════════════════════════════════════════════════════╗
║                     KiClaw Live Engineering Workbench                ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEFT  (this terminal)   →  you + AI / kiclaw chat commands           ║
║  RIGHT (KiCad window)    →  live schematic / PCB canvas               ║
║                                                                      ║
║  Prompt example: "make me a custom PCB for an STM32 breakout"          ║
║  AI uses MCP tools; changes apply via file or live IPC.              ║
╚══════════════════════════════════════════════════════════════════════╝
"""


def start_engineering_session(
    project: str | Path | None = None,
    *,
    create_name: str | None = None,
    create_directory: str | Path | None = None,
    launch: bool = True,
    mode: str = "live",
    arrange_windows: bool = True,
    open_board: bool = True,
) -> dict[str, Any]:
    """Open a product session: optional project create, set active, launch KiCad, report readiness.

    Hybrid live model (see docs/PRODUCT.md): file-first safety + best-effort visual update,
    not full unofficial GUI puppetry.
    """
    steps: list[dict[str, Any]] = []
    project_path: Path | None = None

    if create_name:
        directory = create_directory or Path.cwd()
        created = create_new_project(directory, create_name)
        steps.append({"create_new_project": created})
        project_path = Path(created["path"])
    elif project:
        opened = open_project_session(project)
        steps.append({"open_project_session": opened})
        project_path = Path(opened["project"]["path"])
    else:
        active = get_active_project()
        steps.append({"get_active_project": active})
        if active.get("path"):
            project_path = Path(active["path"])

    set_mode = set_agent_mode(mode)
    steps.append({"set_agent_mode": set_mode})

    caps = capability_report()
    steps.append({"capability_report": {
        "kicad_cli": caps.get("kicad_cli"),
        "ipc": {
            "available": caps.get("ipc", {}).get("available"),
            "binding_available": caps.get("ipc", {}).get("binding_available"),
            "board_api_available": caps.get("ipc", {}).get("board_api_available"),
            "reason": caps.get("ipc", {}).get("reason"),
        },
        "selected_for_auto": caps.get("pcb_backend_policy", {}).get("selected_for_auto"),
    }})

    info = project_info(project_path) if project_path else None
    board = info["boards"][0] if info and info.get("boards") else None
    schematic = info["schematics"][0] if info and info.get("schematics") else None

    launch_result = None
    if launch:
        launch_result = launch_kicad(
            project_path if project_path else None,
            open_board=open_board,
            board=board,
        )
        steps.append({"launch_kicad": launch_result})
        # Prefer board path reported by launcher when available
        if launch_result and launch_result.get("board_file"):
            board = launch_result["board_file"]

    layout_result = None
    if arrange_windows and launch:
        layout_result = arrange_side_by_side()
        steps.append({"arrange_side_by_side": layout_result})

    status = live_status()
    steps.append({"live_status": {
        "live_ready": status.get("live_ready"),
        "file_backend": status.get("file_backend"),
        "instructions": status.get("instructions"),
    }})

    guide = _split_screen_guide(
        project_path=str(project_path) if project_path else None,
        board=board,
        live_ready=bool(status.get("live_ready")),
        launched=bool(launch_result and launch_result.get("ok")),
        layout_ok=bool(layout_result and layout_result.get("ok")),
    )

    return {
        "ok": True,
        "product": "KiClaw Hybrid Live Engineering Workbench",
        "architecture": "hybrid_live",
        "principle": "File-first safety + best-effort visual update; no fake full GUI control.",
        "project": str(project_path) if project_path else None,
        "board": board,
        "schematic": schematic,
        "live_ready": status.get("live_ready"),
        "launched_kicad": bool(launch_result and launch_result.get("ok")),
        "opened_board": (launch_result or {}).get("opened_board") or (launch_result or {}).get("opened"),
        "window_layout": layout_result,
        "mode": mode,
        "steps": steps,
        "guide": guide,
        "banner": PRODUCT_BANNER.strip(),
        "next_user_actions": [
            "Keep THIS terminal on the LEFT and KiCad on the RIGHT (layout attempted automatically on macOS).",
            "In KiCad: confirm the board is open in PCB Editor; enable Preferences → Plugins → API Server for better live feedback.",
            "Type in `kiclaw chat` or connect an AI MCP client (`kiclaw workbench --then serve` or `kiclaw serve`).",
            "Mutation tools auto-attach hybrid_live narration (what changed + where to look + reload path).",
            "Prompt example: make a custom PCB / move a part / run analysis / export fab files.",
        ],
        "suggestions": suggest_next_actions(str(project_path) if project_path else None).get("suggestions"),
    }


def _split_screen_guide(
    *,
    project_path: str | None,
    board: str | None,
    live_ready: bool,
    launched: bool,
    layout_ok: bool = False,
) -> str:
    lines = [
        PRODUCT_BANNER.strip(),
        "",
        "## Hybrid live model (official)",
        "Serious edits are file-backed (snapshot + atomic + verify).",
        "Visual update is best-effort IPC refresh, else clear reload guidance.",
        "We do NOT claim full mouse/toolbar automation of KiCad.",
        "",
        "## Session",
        f"- Project: {project_path or '(none — pass a path or use --new NAME)'}",
        f"- Board:   {board or '(none yet)'}",
        f"- KiCad:   {'launched' if launched else 'not launched'}",
        f"- Window layout: {'side-by-side attempted' if layout_ok else 'arrange manually (terminal left, KiCad right)'}",
        f"- Live IPC ready: {live_ready}",
        "",
        "## How to work",
        "1. LEFT: this terminal (`kiclaw chat` or AI via MCP `serve`).",
        "2. RIGHT: KiCad canvas (PCB/Schematic).",
        "3. Describe what you want; agent edits safely.",
        "4. Watch KiCad update (IPC when ready; else reload when told).",
        "",
        "## Commands here (`kiclaw chat`)",
        "help | doctor | status | start [path] | new NAME | open PATH | board PATH",
        "launch | open-board [PATH] | layout | analyze | review | summary",
        "move REF X Y | refresh [path] | reload [path] | drc | save | quit",
        "",
        "## Live feedback checklist (optional upgrade)",
        "□ KiCad running with project open",
        "□ Preferences → Plugins → API Server enabled",
        "□ Board open in PCB Editor (use `open-board` if not)",
        "□ kiclaw[ipc] installed",
        "□ `status` shows live_ready true",
        "",
        "## Example prompts",
        '- "Summarize this board and run analysis"',
        '- "Move U1 5mm right and tell me what to look at"',
        '- "Add decoupling notes / export BOM"',
    ]
    return "\n".join(lines) + "\n"


def print_session(result: dict[str, Any]) -> None:
    print(result.get("guide") or result.get("banner") or "")
    print("--- session JSON summary ---")
    summary = {k: result[k] for k in (
        "ok", "product", "project", "board", "live_ready", "launched_kicad", "mode", "next_user_actions"
    ) if k in result}
    print(json.dumps(summary, indent=2))


def run_chat_repl(project: str | Path | None = None) -> None:
    """Local interactive terminal for the left-side of the split-screen product."""
    print(PRODUCT_BANNER)
    print("KiClaw chat REPL — type `help`. Ctrl-D or `quit` to exit.\n")
    state: dict[str, Any] = {
        "project": str(project) if project else (get_active_project().get("path")),
        "board": None,
    }
    if state["project"]:
        try:
            info = project_info(state["project"])
            state["board"] = info["boards"][0] if info["boards"] else None
            print(f"Active project: {state['project']}")
            if state["board"]:
                print(f"Active board:   {state['board']}")
        except Exception as exc:
            print(f"(could not load project: {exc})")
    print()

    while True:
        try:
            line = input("kiclaw> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if not line:
            continue
        if line in {"quit", "exit", "q"}:
            print("bye")
            break
        try:
            response = _dispatch_chat(line, state)
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, indent=2, default=str))
        print()


def _dispatch_chat(line: str, state: dict[str, Any]) -> dict[str, Any]:
    parts = shlex.split(line)
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in {"help", "?"}:
        return {
            "ok": True,
            "commands": {
                "help": "this help",
                "doctor": "capability matrix",
                "status": "live + session status",
                "start [path]": "start engineering session (launch KiCad + open board + layout)",
                "new NAME [DIR]": "create project and open session",
                "open PATH": "set active project",
                "board PATH": "set active board file",
                "launch": "launch KiCad for current project (opens board when known)",
                "open-board [PATH]": "open board (or path) in KiCad PCB Editor",
                "layout": "re-apply side-by-side window layout",
                "analyze": "run deep analysis on active board",
                "review": "review active project",
                "move REF X Y": "move footprint (safe file path + hybrid narration)",
                "refresh [path]": "post-edit visual update / reload guidance",
                "reload [path]": "alias for refresh — tell user/agent how to see disk changes",
                "summary": "board summary stats",
                "save": "save project session",
                "close": "close active project session",
                "quit": "exit chat",
            },
            "product_hint": "Hybrid live: safe file edits + best-effort KiCad visual update. Terminal LEFT, KiCad RIGHT. MCP mutations auto-attach hybrid_live.",
        }

    if cmd == "doctor":
        return capability_report()

    if cmd == "status":
        return {
            "ok": True,
            "state": state,
            "active": get_active_project(),
            "live": live_status(),
        }

    if cmd == "start":
        path = args[0] if args else state.get("project")
        result = start_engineering_session(path, launch=True, mode="live")
        if result.get("project"):
            state["project"] = result["project"]
        if result.get("board"):
            state["board"] = result["board"]
        print(result.get("guide", ""))
        return {k: result[k] for k in result if k not in {"steps", "guide", "banner"}}

    if cmd == "new":
        if not args:
            return {"ok": False, "error": "usage: new NAME [DIR]"}
        name = args[0]
        directory = args[1] if len(args) > 1 else str(Path.cwd())
        created = create_new_project(directory, name)
        state["project"] = created["path"]
        info = project_info(created["path"])
        state["board"] = info["boards"][0] if info["boards"] else None
        session = start_engineering_session(created["path"], launch=True, mode="live")
        print(session.get("guide", ""))
        return {"ok": True, "created": created, "session": {k: session[k] for k in ("live_ready", "launched_kicad", "project", "board")}}

    if cmd == "open":
        if not args:
            return {"ok": False, "error": "usage: open PATH"}
        opened = open_project_session(args[0])
        state["project"] = opened["project"]["path"]
        state["board"] = opened["project"]["boards"][0] if opened["project"]["boards"] else None
        return opened

    if cmd == "board":
        if not args:
            return {"ok": False, "error": "usage: board PATH.kicad_pcb"}
        state["board"] = str(Path(args[0]).expanduser().resolve())
        return {"ok": True, "board": state["board"]}

    if cmd == "launch":
        board = state.get("board")
        return launch_kicad(state.get("project"), open_board=True, board=board)

    if cmd in {"open-board", "open_board", "pcb"}:
        target = args[0] if args else (state.get("board") or _require_board(state))
        state["board"] = str(Path(target).expanduser().resolve())
        return open_in_kicad(state["board"])

    if cmd == "analyze":
        board = state.get("board") or _require_board(state)
        return run_analysis(board)

    if cmd == "review":
        project = state.get("project") or _require_project(state)
        return review_project(project)

    if cmd == "summary":
        board = state.get("board") or _require_board(state)
        return board_summary(board)

    if cmd == "move":
        if len(args) < 3:
            return {"ok": False, "error": "usage: move REF X Y"}
        board = state.get("board") or _require_board(state)
        ref, x, y = args[0], float(args[1]), float(args[2])
        mutation = move_footprint(board, ref, x, y, backend="auto")
        narration = narrate_mutation(
            action="move_footprint",
            path=board,
            summary=f"Moved footprint `{ref}` to ({x}, {y}).",
            look_at=f"PCB canvas near `{ref}`",
            transaction_id=mutation.get("transaction_id"),
            snapshot_id=mutation.get("snapshot_id"),
            verification_ok=(mutation.get("verification") or {}).get("ok"),
            backend=mutation.get("backend") or "file",
            refresh=True,
        )
        return {"ok": mutation.get("ok", False), "mutation": mutation, "narration": narration}

    if cmd in {"refresh", "reload"}:
        target = args[0] if args else (state.get("board") or state.get("project"))
        result = refresh_kicad_view(target)
        # Always surface a plain user-facing line for the left terminal.
        if result.get("user_action"):
            result = dict(result)
            result["user_message"] = result["user_action"]
        return result

    if cmd == "layout":
        return arrange_side_by_side()

    if cmd == "drc":
        board = state.get("board") or _require_board(state)
        return run_check("drc", board)

    if cmd == "save":
        return save_project(state.get("project"), backend="auto")

    if cmd == "close":
        state["project"] = None
        state["board"] = None
        return close_project()

    return {
        "ok": False,
        "error": f"unknown command: {cmd}",
        "hint": "type `help` — or use an AI MCP client with `kiclaw serve` for natural language",
    }


def _require_project(state: dict[str, Any]) -> str:
    if not state.get("project"):
        raise ValueError("no active project — use: open PATH  or  new NAME")
    return state["project"]


def _require_board(state: dict[str, Any]) -> str:
    if state.get("board"):
        return state["board"]
    project = _require_project(state)
    info = project_info(project)
    if not info["boards"]:
        raise ValueError("project has no .kicad_pcb files")
    state["board"] = info["boards"][0]
    return state["board"]
