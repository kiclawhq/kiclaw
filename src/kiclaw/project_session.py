"""Project lifecycle: create, save, close (file-first + optional live save)."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import KiClawError, find_kicad_cli, ipc_capability, project_info, resolve_path, _atomic_write

_SESSION_PATH = Path.home() / ".kiclaw" / "active-project.json"

def _minimal_pro(name: str) -> str:
    return json.dumps(
        {
            "board": {"design_settings": {"defaults": {}, "rules": {}}, "layer_presets": [], "viewports": []},
            "boards": [],
            "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
            "meta": {"filename": f"{name}.kicad_pro", "version": 1},
            "net_settings": {
                "classes": [
                    {
                        "name": "Default",
                        "clearance": 0.2,
                        "track_width": 0.25,
                        "via_diameter": 0.8,
                        "via_drill": 0.4,
                    }
                ],
                "meta": {"version": 3},
            },
            "schematic": {"meta": {"version": 1}, "drawing": {}},
            "sheets": [],
            "text_variables": {},
        },
        indent=2,
    ) + "\n"

MINIMAL_SCH = """(kicad_sch
\t(version 20250114)
\t(generator "kiclaw")
\t(generator_version "0.1")
\t(uuid "{uuid}")
\t(paper "A4")
\t(lib_symbols)
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
"""

MINIMAL_PCB = """(kicad_pcb
\t(version 20241229)
\t(generator "kiclaw")
\t(generator_version "0.1")
\t(general
\t\t(thickness 1.6)
\t\t(legacy_teardrops no)
\t)
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(31 "B.Cu" signal)
\t\t(36 "B.SilkS" user "B.Silkscreen")
\t\t(37 "F.SilkS" user "F.Silkscreen")
\t\t(38 "B.Mask" user)
\t\t(39 "F.Mask" user)
\t\t(40 "Dwgs.User" user "User.Drawings")
\t\t(41 "Cmts.User" user "User.Comments")
\t\t(44 "Edge.Cuts" user)
\t\t(46 "B.CrtYd" user "B.Courtyard")
\t\t(47 "F.CrtYd" user "F.Courtyard")
\t\t(48 "B.Fab" user)
\t\t(49 "F.Fab" user)
\t)
\t(setup
\t\t(pad_to_mask_clearance 0)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(pcbplotparams
\t\t\t(layerselection 0x00010fc_ffffffff)
\t\t\t(plot_on_all_layers_selection 0x0000000_00000000)
\t\t\t(disableapertmacros no)
\t\t\t(usegerberextensions no)
\t\t\t(usegerberattributes yes)
\t\t\t(usegerberadvancedattributes yes)
\t\t\t(creategerberjobfile yes)
\t\t\t(dashed_line_dash_ratio 12.000000)
\t\t\t(dashed_line_gap_ratio 3.000000)
\t\t\t(svgprecision 4)
\t\t\t(plotframeref no)
\t\t\t(viasonmask no)
\t\t\t(mode 1)
\t\t\t(useauxorigin no)
\t\t\t(hpglpennumber 1)
\t\t\t(hpglpenspeed 20)
\t\t\t(hpglpendiameter 15.000000)
\t\t\t(pdf_front_fp_property_popups yes)
\t\t\t(pdf_back_fp_property_popups yes)
\t\t\t(pdf_metadata yes)
\t\t\t(pdf_single_document no)
\t\t\t(dxfpolygonmode yes)
\t\t\t(dxfimperialunits yes)
\t\t\t(dxfusepcbnewfont yes)
\t\t\t(psnegative no)
\t\t\t(psa4output no)
\t\t\t(plotreference yes)
\t\t\t(plotvalue yes)
\t\t\t(plotfptext yes)
\t\t\t(plotinvisibletext no)
\t\t\t(sketchpadsonfab no)
\t\t\t(subtractmaskfromsilk no)
\t\t\t(outputformat 1)
\t\t\t(mirror no)
\t\t\t(drillshape 1)
\t\t\t(scaleselection 1)
\t\t\t(outputdirectory "")
\t\t)
\t)
\t(net 0 "")
)
"""


def _set_active_project(path: Path | None) -> None:
    _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    if path is None:
        if _SESSION_PATH.exists():
            _SESSION_PATH.unlink()
        return
    _atomic_write(_SESSION_PATH, json.dumps({
        "path": str(path),
        "set_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")


def get_active_project() -> dict[str, Any]:
    if not _SESSION_PATH.exists():
        return {"ok": True, "active": False, "path": None}
    data = json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
    path = data.get("path")
    exists = Path(path).exists() if path else False
    return {"ok": True, "active": exists, "path": path if exists else None, "meta": data}


def create_new_project(
    directory: str | Path,
    name: str,
    template: str | Path | None = None,
) -> dict[str, Any]:
    """Create a new KiCad project from a template directory or a minimal scaffold."""
    if not name or any(c in name for c in '/\\'):
        raise KiClawError("name must be a simple project name without path separators")
    root = resolve_path(directory) / name
    if root.exists() and any(root.iterdir()):
        raise KiClawError(f"Target is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    used_template = None
    if template is not None:
        src = resolve_path(template)
        if not src.is_dir():
            raise KiClawError(f"Template directory not found: {src}")
        for item in src.iterdir():
            dest = root / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        used_template = str(src)
        # rename main files if single-stem template
        for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
            matches = list(root.glob(f"*{suffix}"))
            if len(matches) == 1 and matches[0].stem != name:
                matches[0].rename(root / f"{name}{suffix}")
    else:
        import uuid
        (root / f"{name}.kicad_pro").write_text(_minimal_pro(name), encoding="utf-8")
        (root / f"{name}.kicad_sch").write_text(MINIMAL_SCH.format(uuid=str(uuid.uuid4())), encoding="utf-8")
        (root / f"{name}.kicad_pcb").write_text(MINIMAL_PCB, encoding="utf-8")

    info = project_info(root)
    _set_active_project(root)
    return {
        "ok": True,
        "path": str(root),
        "name": name,
        "template": used_template,
        "project": info,
        "active": True,
        "note": "Minimal scaffold is valid for tooling; open in KiCad to refine project settings.",
    }


def open_project_session(path: str | Path) -> dict[str, Any]:
    """Set the active project session to an existing project."""
    info = project_info(path)
    root = Path(info["path"])
    _set_active_project(root)
    return {"ok": True, "active": True, "project": info}


def close_project() -> dict[str, Any]:
    previous = get_active_project()
    _set_active_project(None)
    return {"ok": True, "closed": previous.get("path"), "active": False}


def save_project(path: str | Path | None = None, backend: str = "auto") -> dict[str, Any]:
    """Persist the project.

    File backend: confirms project files exist (disk is already the source of truth for file edits).
    IPC backend: attempts a live board save when KiCad IPC is available.
    """
    if path is None:
        active = get_active_project()
        if not active.get("path"):
            raise KiClawError("No active project; pass path or open_project_session first")
        path = active["path"]
    info = project_info(path)
    result: dict[str, Any] = {
        "ok": True,
        "project": info,
        "backend": "file",
        "saved": [],
        "live_saved": False,
    }
    for key in ("boards", "schematics", "project_files"):
        for item in info[key]:
            p = Path(item)
            if p.is_file():
                result["saved"].append({"path": str(p), "sha256_hint": p.stat().st_size, "mtime": p.stat().st_mtime})

    if backend in {"auto", "ipc"}:
        cap = ipc_capability()
        if cap.get("available") and cap.get("board_api_available"):
            try:
                from kipy import KiCad
                connection = KiCad(timeout_ms=2000)
                board = connection.get_board()
                # kipy board save APIs vary; try common names
                saved = False
                for method_name in ("save", "save_as", "Save"):
                    method = getattr(board, method_name, None)
                    if callable(method):
                        try:
                            method()
                            saved = True
                            break
                        except TypeError:
                            # maybe needs path
                            try:
                                method(str(info["boards"][0]) if info["boards"] else "")
                                saved = True
                                break
                            except Exception:
                                continue
                        except Exception:
                            continue
                # project-level save
                if not saved:
                    project = connection.get_project() if hasattr(connection, "get_project") else None
                    if project is not None:
                        for method_name in ("save", "Save"):
                            method = getattr(project, method_name, None)
                            if callable(method):
                                try:
                                    method()
                                    saved = True
                                    break
                                except Exception:
                                    continue
                result["backend"] = "ipc" if saved else "file"
                result["live_saved"] = saved
                result["ipc"] = {"attempted": True, "saved": saved, "capability": cap}
                if backend == "ipc" and not saved:
                    result["ok"] = False
                    result["reason"] = "IPC connected but no save method succeeded; file backend remains source of truth."
            except Exception as exc:
                result["ipc"] = {"attempted": True, "saved": False, "error": f"{type(exc).__name__}: {exc}"}
                if backend == "ipc":
                    result["ok"] = False
                    result["reason"] = str(exc)
        elif backend == "ipc":
            result["ok"] = False
            result["reason"] = "IPC save requested but live session unavailable"
            result["capability"] = cap

    result["note"] = (
        "File-backed mutations are already on disk after each guarded commit. "
        "Live IPC save only applies to unsaved GUI document state."
    )
    return result
