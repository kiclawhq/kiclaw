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
from .live import launch_kicad, live_status
from .project_session import (
    close_project,
    create_new_project,
    get_active_project,
    open_project_session,
    save_project,
)


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
) -> dict[str, Any]:
    """Open a product session: optional project create, set active, launch KiCad, report readiness."""
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

    launch_result = None
    if launch:
        launch_result = launch_kicad(project_path if project_path else None)
        steps.append({"launch_kicad": launch_result})

    status = live_status()
    steps.append({"live_status": {
        "live_ready": status.get("live_ready"),
        "file_backend": status.get("file_backend"),
        "instructions": status.get("instructions"),
    }})

    info = project_info(project_path) if project_path else None
    board = info["boards"][0] if info and info.get("boards") else None

    guide = _split_screen_guide(
        project_path=str(project_path) if project_path else None,
        board=board,
        live_ready=bool(status.get("live_ready")),
        launched=bool(launch_result and launch_result.get("ok")),
    )

    return {
        "ok": True,
        "product": "KiClaw Live Engineering Workbench",
        "project": str(project_path) if project_path else None,
        "board": board,
        "live_ready": status.get("live_ready"),
        "launched_kicad": bool(launch_result and launch_result.get("ok")),
        "mode": mode,
        "steps": steps,
        "guide": guide,
        "banner": PRODUCT_BANNER.strip(),
        "next_user_actions": [
            "Arrange windows: terminal LEFT, KiCad RIGHT",
            "In KiCad: Preferences → Plugins → API Server → Enable (for live canvas)",
            "Open the board in PCB Editor",
            "In this terminal: run `kiclaw chat` for local commands OR connect an AI client to `kiclaw serve`",
            "Prompt the AI: e.g. make a custom PCB / move footprint / run analysis",
        ],
        "suggestions": suggest_next_actions(str(project_path) if project_path else None).get("suggestions"),
    }


def _split_screen_guide(*, project_path: str | None, board: str | None, live_ready: bool, launched: bool) -> str:
    lines = [
        PRODUCT_BANNER.strip(),
        "",
        "## Session",
        f"- Project: {project_path or '(none — pass a path or use --new NAME)'}",
        f"- Board:   {board or '(none yet)'}",
        f"- KiCad:   {'launched' if launched else 'not launched'}",
        f"- Live IPC ready: {live_ready}",
        "",
        "## How to work (product layout)",
        "1. Put THIS terminal on the left half of the screen.",
        "2. Put KiCad on the right half (PCB Editor for board work).",
        "3. Talk to AI in the left terminal (MCP client) or type commands in `kiclaw chat`.",
        "4. Watch the right-side KiCad window update:",
        "   - Live IPC moves appear immediately when API Server is on.",
        "   - File edits apply on disk; reload the board in KiCad if the view is stale.",
        "",
        "## Two left-terminal options",
        "A) AI agent (recommended for 'make me a custom PCB'):",
        "     Terminal:  kiclaw serve",
        "     Connect Claude/Codex/Cursor MCP to that process, then chat naturally.",
        "B) Local command REPL (no cloud model required):",
        "     Terminal:  kiclaw chat",
        "     Then: help | doctor | open PATH | analyze | move REF X Y | review | status",
        "",
        "## Live canvas checklist (for true on-screen edits)",
        "□ KiCad running",
        "□ Preferences → Plugins → API Server → enabled",
        "□ Board open in PCB Editor",
        "□ kiclaw[ipc] installed (kicad-python)",
        "□ `kiclaw doctor` shows ipc.available / board_api_available",
        "",
        "## Example prompts to your AI (left side)",
        '- "Open this project and summarize the board"',
        '- "Make me a custom PCB outline 50x50mm with 4 mounting holes"',
        '- "Move J1 by 1mm and run DRC"',
        '- "Run deep analysis and list protection gaps"',
        '- "Export BOM and position file"',
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
                "start [path]": "start engineering session (launch KiCad)",
                "new NAME [DIR]": "create project and open session",
                "open PATH": "set active project",
                "board PATH": "set active board file",
                "launch": "launch KiCad for current project",
                "analyze": "run deep analysis on active board",
                "review": "review active project",
                "move REF X Y": "move footprint (file backend; live if IPC ready)",
                "summary": "board summary stats",
                "save": "save project session",
                "close": "close active project session",
                "quit": "exit chat",
            },
            "product_hint": "Keep KiCad on the other half of the screen while you type here.",
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
        return launch_kicad(state.get("project"))

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
        return move_footprint(board, ref, x, y, backend="auto")

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
