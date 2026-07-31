"""Post-edit visual update — make file-backed changes feel live.

Order of preference:
1. Official IPC refresh/reload if board document is open
2. Clear reload guidance for the user
3. Optional window screenshot (macOS) for agent feedback
4. Always narrate what changed and where to look
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import KiClawError, board_summary, ipc_capability, resolve_path, schematic_summary
from .live import live_status


def refresh_kicad_view(
    path: str | Path | None = None,
    *,
    kind: str = "auto",
    take_screenshot: bool = False,
    screenshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Best-effort visual refresh after a file-backed edit.

    Does not fake success. Reports which mechanism was used.
    """
    result: dict[str, Any] = {
        "ok": True,
        "path": str(path) if path else None,
        "kind": kind,
        "mechanism": None,
        "live_status": live_status(),
        "user_action": None,
        "look_at": None,
        "screenshot": None,
        "notes": [],
    }

    resolved: Path | None = None
    if path is not None:
        resolved = Path(path).expanduser().resolve()
        result["path"] = str(resolved)
        if kind == "auto":
            if resolved.suffix == ".kicad_pcb":
                kind = "pcb"
            elif resolved.suffix == ".kicad_sch":
                kind = "schematic"
            else:
                kind = "project"
        result["kind"] = kind

    cap = ipc_capability()
    ipc_attempt = _try_ipc_refresh(resolved, kind, cap)
    result["ipc_attempt"] = ipc_attempt

    if ipc_attempt.get("refreshed"):
        result["mechanism"] = "ipc_refresh"
        result["notes"].append("Asked KiCad via IPC to acknowledge the open document after disk change.")
        result["user_action"] = (
            "If the view still looks stale, focus PCB/Schematic Editor and use File → Revert or reopen the file."
        )
    elif cap.get("connection_available"):
        result["mechanism"] = "ipc_connected_no_document_reload"
        result["user_action"] = (
            "KiCad IPC is up but could not reload the document automatically. "
            "Open the edited file in PCB/Schematic Editor, then File → Revert (or close and reopen) to see disk changes."
        )
        result["notes"].append(ipc_attempt.get("reason") or "No reload API succeeded.")
    else:
        result["mechanism"] = "file_reload_guidance"
        result["user_action"] = (
            "Edits are on disk. In KiCad: open or focus the project, then reload the board/schematic "
            "(File → Revert or reopen) to see updates. Enable API Server for better live feedback next time."
        )

    if resolved is not None and resolved.suffix == ".kicad_pcb" and resolved.is_file():
        try:
            summary = board_summary(resolved)
            result["look_at"] = {
                "type": "pcb",
                "path": str(resolved),
                "statistics": summary.get("statistics"),
                "sha256": summary.get("sha256"),
                "hint": "Check the canvas for moved footprints, new tracks/vias, or outline changes.",
            }
        except Exception as exc:
            result["look_at"] = {"type": "pcb", "error": str(exc)}
    elif resolved is not None and resolved.suffix == ".kicad_sch" and resolved.is_file():
        try:
            summary = schematic_summary(resolved)
            result["look_at"] = {
                "type": "schematic",
                "path": str(resolved),
                "top_level_counts": summary.get("top_level_counts"),
                "sha256": summary.get("sha256"),
                "hint": "Check the sheet for new symbols, wires, and labels.",
            }
        except Exception as exc:
            result["look_at"] = {"type": "schematic", "error": str(exc)}

    if take_screenshot:
        shot = capture_kicad_screenshot(screenshot_path)
        result["screenshot"] = shot
        if not shot.get("ok"):
            result["notes"].append(shot.get("reason") or "Screenshot unavailable.")

    result["agent_narration_template"] = (
        "I applied a safe file-backed change"
        + (f" to `{resolved.name}`" if resolved else "")
        + f". Visual update path: **{result['mechanism']}**. "
        + (result.get("user_action") or "")
        + " Snapshot/transaction details are in the mutation result if this followed an edit."
    )
    return result


def _try_ipc_refresh(path: Path | None, kind: str, cap: dict[str, Any]) -> dict[str, Any]:
    if not cap.get("connection_available") and not cap.get("available"):
        return {"refreshed": False, "reason": "No KiCad IPC connection."}
    try:
        from kipy import KiCad

        connection = KiCad(timeout_ms=1500)
        connection.ping()
        board = None
        try:
            board = connection.get_board()
        except Exception as exc:
            return {
                "refreshed": False,
                "reason": f"Connected but no active board document: {type(exc).__name__}: {exc}",
                "hint": "Open the .kicad_pcb in PCB Editor with API Server enabled.",
            }

        # Best-effort: poke common refresh/reload methods if present
        methods_tried = []
        for name in ("reload", "Reload", "refresh", "Refresh", "update", "Update"):
            method = getattr(board, name, None)
            if callable(method):
                methods_tried.append(name)
                try:
                    method()
                    return {"refreshed": True, "method": f"board.{name}", "methods_tried": methods_tried}
                except TypeError:
                    if path is not None:
                        try:
                            method(str(path))
                            return {"refreshed": True, "method": f"board.{name}(path)", "methods_tried": methods_tried}
                        except Exception:
                            continue
                except Exception:
                    continue

        # Project-level
        try:
            project = connection.get_project()
            for name in ("reload", "Reload", "save", "Save"):
                method = getattr(project, name, None) if project is not None else None
                if callable(method):
                    methods_tried.append(f"project.{name}")
                    try:
                        method()
                        return {
                            "refreshed": True,
                            "method": f"project.{name}",
                            "methods_tried": methods_tried,
                            "note": "Project method invoked; may not fully re-read disk into the editor.",
                        }
                    except Exception:
                        continue
        except Exception:
            pass

        return {
            "refreshed": False,
            "reason": "IPC board is open but no reload/refresh method succeeded on this kipy/KiCad build.",
            "methods_tried": methods_tried,
            "board_name": str(getattr(board, "name", "")),
        }
    except Exception as exc:
        return {"refreshed": False, "reason": f"{type(exc).__name__}: {exc}"}


def capture_kicad_screenshot(output: str | Path | None = None) -> dict[str, Any]:
    """Best-effort screenshot of the KiCad front window (macOS screencapture)."""
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = Path.home() / ".kiclaw" / "screenshots" / f"kicad-{stamp}.png"
    dest = Path(output).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    # macOS: capture frontmost window interactively is not ideal; try app window by name
    screencapture = shutil.which("screencapture")
    if not screencapture:
        return {"ok": False, "reason": "screencapture not available (non-macOS or missing)."}

    # -l requires window id; use AppleScript to get KiCad window id when possible
    script = """
    tell application "System Events"
      if not (exists process "KiCad") then return "NO_KICAD"
      tell process "KiCad"
        set frontmost to true
        delay 0.2
        if (count of windows) is 0 then return "NO_WINDOW"
        return id of window 1
      end tell
    end tell
    """
    try:
        proc = subprocess.run(["osascript", "-e", script], text=True, capture_output=True, check=False, timeout=10)
        wid = (proc.stdout or "").strip()
        if wid in {"", "NO_KICAD", "NO_WINDOW"} or not wid.isdigit():
            # Full-screen fallback is too invasive; report guidance only
            return {
                "ok": False,
                "reason": f"Could not resolve KiCad window id ({wid or proc.stderr.strip()}). Open KiCad and grant Accessibility if needed.",
                "path": str(dest),
            }
        shot = subprocess.run(
            [screencapture, "-l", wid, str(dest)],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
        if shot.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
            return {"ok": True, "path": str(dest), "bytes": dest.stat().st_size, "window_id": wid}
        return {"ok": False, "reason": shot.stderr.strip() or "screencapture failed", "path": str(dest)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "path": str(dest)}


def narrate_mutation(
    *,
    action: str,
    path: str | Path | None = None,
    summary: str,
    look_at: str | None = None,
    transaction_id: str | None = None,
    snapshot_id: str | None = None,
    verification_ok: bool | None = None,
    backend: str = "file",
    refresh: bool = True,
) -> dict[str, Any]:
    """Build the standard post-edit agent narration + optional visual refresh."""
    visual = refresh_kicad_view(path, take_screenshot=False) if refresh else None
    lines = [
        summary.strip(),
        f"Backend: **{backend}**.",
    ]
    if transaction_id:
        lines.append(f"Transaction: `{transaction_id}`.")
    if snapshot_id:
        lines.append(f"Snapshot: `{snapshot_id}` (restore if needed).")
    if verification_ok is True:
        lines.append("Verification: passed (or reported clean).")
    elif verification_ok is False:
        lines.append("Verification: reported issues — review before manufacturing.")
    if look_at:
        lines.append(f"**Look at:** {look_at}")
    elif visual and visual.get("look_at"):
        hint = visual["look_at"].get("hint")
        if hint:
            lines.append(f"**Look at:** {hint}")
    if visual:
        lines.append(f"Visual update path: `{visual.get('mechanism')}`.")
        if visual.get("user_action"):
            lines.append(visual["user_action"])
    lines.append("Would you like me to adjust anything or restore the snapshot?")

    return {
        "ok": True,
        "action": action,
        "path": str(path) if path else None,
        "message": "\n\n".join(lines),
        "visual_update": visual,
    }


def arrange_side_by_side() -> dict[str, Any]:
    """Best-effort macOS window layout: terminal left, KiCad right."""
    script = r'''
    tell application "System Events"
      set termName to ""
      repeat with procName in {"Terminal", "iTerm2", "Alacritty", "Kitty", "WezTerm", "Warp", "Code", "Cursor", "Ghostty"}
        if exists process procName then
          set termName to procName as string
          exit repeat
        end if
      end repeat
      if termName is "" then return "NO_TERMINAL"
      if not (exists process "KiCad") then return "NO_KICAD"

      tell application "Finder"
        set screenBounds to bounds of window of desktop
      end tell
      set screenW to item 3 of screenBounds
      set screenH to item 4 of screenBounds
      set mid to screenW / 2

      try
        tell process termName
          set frontmost to true
          if (count of windows) > 0 then
            set position of window 1 to {0, 22}
            set size of window 1 to {mid - 4, screenH - 22}
          end if
        end tell
      end try

      try
        tell process "KiCad"
          set frontmost to true
          if (count of windows) > 0 then
            set position of window 1 to {mid, 22}
            set size of window 1 to {screenW - mid, screenH - 22}
          end if
        end tell
      end try
      return "OK:" & termName
    end tell
    '''
    if not shutil.which("osascript"):
        return {"ok": False, "reason": "Window layout only implemented for macOS (osascript)."}
    try:
        proc = subprocess.run(["osascript", "-e", script], text=True, capture_output=True, check=False, timeout=15)
        out = (proc.stdout or "").strip()
        if out.startswith("OK:"):
            return {
                "ok": True,
                "layout": "side_by_side",
                "terminal": out.split(":", 1)[1],
                "note": "Terminal left, KiCad right (best-effort). Grant Accessibility if layout did not apply.",
            }
        return {
            "ok": False,
            "reason": out or proc.stderr.strip() or "layout failed",
            "hint": "Manually put the agent terminal on the left and KiCad on the right.",
        }
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
