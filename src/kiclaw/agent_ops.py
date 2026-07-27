"""Agent mode, help, and convenience helpers for MCP progressive disclosure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import capability_report, project_info, resolve_path

_MODE_PATH = Path.home() / ".kiclaw" / "agent-mode.json"
_VALID_MODES = ("review", "edit", "live", "fab", "inspect")


def get_agent_mode() -> dict[str, Any]:
    if not _MODE_PATH.exists():
        return {"ok": True, "mode": "inspect", "source": "default", "valid_modes": list(_VALID_MODES)}
    data = json.loads(_MODE_PATH.read_text(encoding="utf-8"))
    return {"ok": True, "mode": data.get("mode", "inspect"), "source": str(_MODE_PATH), "valid_modes": list(_VALID_MODES), **{k: v for k, v in data.items() if k != "mode"}}


def set_agent_mode(mode: str, require_approval: bool = False) -> dict[str, Any]:
    if mode not in _VALID_MODES:
        return {"ok": False, "reason": f"mode must be one of {_VALID_MODES}", "valid_modes": list(_VALID_MODES)}
    _MODE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mode": mode, "require_approval": require_approval}
    _MODE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **payload, "path": str(_MODE_PATH)}


def require_approval(enabled: bool = True) -> dict[str, Any]:
    current = get_agent_mode()
    mode = current.get("mode", "inspect")
    return set_agent_mode(mode, require_approval=enabled)


# Static help registry for public tools (kept short; MCP schema remains source of truth).
_TOOL_HELP: dict[str, dict[str, str]] = {
    "capability_report": {"summary": "Report KiCad CLI/IPC/file backend availability.", "category": "inspect"},
    "run_analysis": {"summary": "Deep structural analysis packs on a board.", "category": "verify"},
    "analyze_power_tree": {"summary": "Power-net inventory from board S-expressions.", "category": "verify"},
    "audit_protection": {"summary": "Connector vs protection-device audit.", "category": "verify"},
    "review_project": {"summary": "Full project review including DRC/ERC/analysis.", "category": "verify"},
    "move_footprint": {"summary": "Guarded footprint move (IPC auto or file).", "category": "edit"},
    "add_track": {"summary": "Insert one copper segment with snapshot+DRC.", "category": "edit"},
    "export_bom": {"summary": "Native KiCad BOM export from schematic.", "category": "export"},
    "export_pos": {"summary": "Component position/CPL file from board.", "category": "export"},
    "create_release_package": {"summary": "Gerbers+drill+BOM+pos+review package.", "category": "export"},
    "launch_kicad": {"summary": "Launch KiCad GUI for live operation (host-dependent).", "category": "ipc"},
    "set_agent_mode": {"summary": "Set inspect/edit/live/fab agent mode.", "category": "meta"},
}


def get_tool_help(name: str) -> dict[str, Any]:
    key = name.strip()
    if key in _TOOL_HELP:
        return {"ok": True, "name": key, **_TOOL_HELP[key]}
    return {
        "ok": True,
        "name": key,
        "summary": "No extended help entry; use list_tool_categories/find_tool and MCP schema.",
        "category": "unknown",
    }


def suggest_next_actions(project: str | None = None) -> dict[str, Any]:
    caps = capability_report()
    mode = get_agent_mode()
    suggestions = [
        {"action": "capability_report", "why": "Confirm KiCad CLI/IPC before any edit."},
        {"action": "open_project", "why": "Identify boards and schematics in scope."},
        {"action": "run_analysis", "why": "Deep structural triage before manufacturing review."},
        {"action": "review_project", "why": "Aggregate DRC/ERC/DFM/analysis findings."},
    ]
    if caps.get("ipc", {}).get("available"):
        suggestions.append({"action": "ipc_session_info", "why": "Live IPC is available; inspect open boards."})
        suggestions.append({"action": "set_agent_mode", "args": {"mode": "live"}, "why": "Enable live mode policy for visible edits."})
    else:
        suggestions.append({
            "action": "launch_kicad",
            "why": "Open KiCad GUI; enable Preferences → Plugins → API Server for live tools.",
        })
    if project:
        try:
            info = project_info(project)
            if info["boards"]:
                suggestions.append({"action": "export_pos", "why": "Prepare CPL once review is clean.", "board": info["boards"][0]})
            if info["schematics"]:
                suggestions.append({"action": "export_bom", "why": "Prepare BOM from schematic.", "schematic": info["schematics"][0]})
        except Exception:
            pass
    if mode.get("mode") == "fab":
        suggestions.append({"action": "create_release_package", "why": "Mode is fab; produce manufacturing package."})
    return {"ok": True, "mode": mode, "capability": caps, "suggestions": suggestions}
