"""Live Visual Mode scaffolding: launch KiCad and honest IPC-gated tools."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .core import KiClawError, capability_report, ipc_capability, resolve_path

MACOS_KICAD = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad")


def launch_kicad(project: str | Path | None = None) -> dict[str, Any]:
    """Launch the KiCad GUI, optionally opening a project file.

    Live tools still require Preferences → Plugins → API Server enabled after launch.
    """
    candidates = []
    configured = os.environ.get("KICLAW_KICAD_GUI")
    if configured:
        candidates.append(Path(configured))
    which = shutil.which("kicad")
    if which:
        candidates.append(Path(which))
    candidates.append(MACOS_KICAD)
    exe = next((c for c in candidates if c.is_file() and os.access(c, os.X_OK)), None)
    if not exe:
        return {
            "ok": False,
            "available": False,
            "reason": "KiCad GUI executable not found. Set KICLAW_KICAD_GUI or install KiCad.",
        }
    cmd = [str(exe)]
    opened = None
    if project is not None:
        path = resolve_path(project)
        if path.is_dir():
            pros = sorted(path.glob("*.kicad_pro"))
            path = pros[0] if pros else path
        if path.is_file():
            cmd.append(str(path))
            opened = str(path)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return {"ok": False, "available": True, "path": str(exe), "reason": str(exc)}
    return {
        "ok": True,
        "available": True,
        "path": str(exe),
        "pid": proc.pid,
        "opened": opened,
        "note": "Enable KiCad API Server (Preferences → Plugins → API Server) for live IPC tools. Install kiclaw[ipc] for kipy bindings.",
        "next": ["ipc_session_info", "capability_report", "set_agent_mode"],
    }


def _live_unavailable(action: str) -> dict[str, Any]:
    cap = ipc_capability()
    return {
        "ok": False,
        "live": False,
        "action": action,
        "available": bool(cap.get("available") and cap.get("board_api_available")),
        "capability": cap,
        "reason": cap.get("reason") or "Live PCB API is not available.",
        "limitation": f"{action} requires a reachable KiCad PCB Editor API session (live-gated).",
    }


def get_selection() -> dict[str, Any]:
    """Live selection probe (best-effort; may be unavailable)."""
    if not ipc_capability().get("available"):
        return _live_unavailable("get_selection")
    try:
        from kipy import KiCad
        connection = KiCad(timeout_ms=1000)
        board = connection.get_board()
        # kipy selection APIs vary by version — report honesty if missing
        selection = getattr(board, "get_selection", None)
        if selection is None:
            return {
                "ok": False,
                "live": True,
                "action": "get_selection",
                "reason": "This kicad-python build does not expose get_selection.",
            }
        items = selection()
        return {"ok": True, "live": True, "count": len(list(items)), "items": [str(i) for i in items]}
    except Exception as exc:
        return {"ok": False, "live": True, "action": "get_selection", "reason": f"{type(exc).__name__}: {exc}"}


def get_view_state() -> dict[str, Any]:
    return _live_unavailable("get_view_state") if not ipc_capability().get("available") else {
        "ok": False,
        "live": True,
        "action": "get_view_state",
        "reason": "Canvas zoom/pan APIs are not stably exposed; use KiCad UI or future Live Visual Mode.",
        "capability": ipc_capability(),
    }


def switch_editor(editor: str) -> dict[str, Any]:
    return {
        "ok": False,
        "live": False,
        "action": "switch_editor",
        "requested": editor,
        "reason": "Editor switching is not available via current KiCad IPC surface; open Schematic/PCB manually.",
        "planned": True,
    }


def select_object(reference: str) -> dict[str, Any]:
    return _live_unavailable("select_object") | {"reference": reference, "planned": True}


def highlight_net(net_name: str) -> dict[str, Any]:
    return _live_unavailable("highlight_net") | {"net_name": net_name, "planned": True}


def highlight_component(reference: str) -> dict[str, Any]:
    return _live_unavailable("highlight_component") | {"reference": reference, "planned": True}


def zoom_to_object(reference: str) -> dict[str, Any]:
    return _live_unavailable("zoom_to_object") | {"reference": reference, "planned": True}


def get_canvas_state() -> dict[str, Any]:
    return get_view_state() | {"action": "get_canvas_state"}


def take_screenshot(output_file: str | Path) -> dict[str, Any]:
    """Best-effort board render via kicad-cli pcb render when available."""
    from .core import find_kicad_cli
    destination = resolve_path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cli = find_kicad_cli()
    if not cli:
        return {"ok": False, "reason": "kicad-cli not found"}
    # render needs a board path — require caller uses export path instead if unknown
    return {
        "ok": False,
        "reason": "take_screenshot requires an explicit board path; use render_board(board, output) instead.",
        "planned_alias": "render_board",
        "output": str(destination),
    }


def render_board(board: str | Path, output_file: str | Path) -> dict[str, Any]:
    """Render PCB to an image via kicad-cli when supported (visual aid for agents)."""
    from .core import find_kicad_cli
    path = resolve_path(board, ".kicad_pcb")
    destination = resolve_path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cli = find_kicad_cli()
    if not cli:
        return {"ok": False, "available": False, "reason": "kicad-cli not found"}
    cmd = [str(cli), "pcb", "render", "--output", str(destination), str(path)]
    try:
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "available": True, "reason": "render timed out"}
    except OSError as exc:
        return {"ok": False, "available": False, "reason": str(exc)}
    return {
        "ok": completed.returncode == 0 and destination.exists(),
        "board": str(path),
        "output": str(destination),
        "exists": destination.exists(),
        "bytes": destination.stat().st_size if destination.exists() else 0,
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
        "note": "Static render, not a live canvas capture.",
    }


def live_status() -> dict[str, Any]:
    """One-shot live readiness summary for agents."""
    caps = capability_report()
    return {
        "ok": True,
        "file_backend": True,
        "live_ready": bool(caps.get("ipc", {}).get("available") and caps.get("ipc", {}).get("board_api_available")),
        "capability": caps,
        "instructions": [
            "1. Call launch_kicad(project) if GUI is closed",
            "2. In KiCad: Preferences → Plugins → API Server → enable",
            "3. Open the target board in PCB Editor",
            "4. pip/uv install kiclaw[ipc] (kicad-python)",
            "5. capability_report / ipc_session_info until live_ready is true",
            "6. Prefer ipc_move_footprint / move_footprint backend=auto for visible moves",
        ],
    }
