"""Manufacturing exports: BOM, position, netlist, release package."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import KiClawError, find_kicad_cli, project_info, resolve_path, run_export, review_project


def _cli() -> Path:
    cli = find_kicad_cli()
    if not cli:
        raise KiClawError("kicad-cli was not found")
    return cli


def export_bom(schematic: str | Path, output_file: str | Path) -> dict[str, Any]:
    """Generate BOM via native kicad-cli sch export bom."""
    path = resolve_path(schematic, ".kicad_sch")
    destination = resolve_path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cli = _cli()
    cmd = [str(cli), "sch", "export", "bom", "--output", str(destination), str(path)]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=180)
    return {
        "ok": completed.returncode == 0 and destination.exists(),
        "kind": "bom",
        "schematic": str(path),
        "output": str(destination),
        "exists": destination.exists(),
        "bytes": destination.stat().st_size if destination.exists() else 0,
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
    }


def export_pos(board: str | Path, output_file: str | Path, side: str = "both", units: str = "mm") -> dict[str, Any]:
    """Generate component position (CPL) file via kicad-cli pcb export pos."""
    if side not in {"front", "back", "both"}:
        raise KiClawError("side must be front, back, or both")
    if units not in {"mm", "in"}:
        raise KiClawError("units must be mm or in")
    path = resolve_path(board, ".kicad_pcb")
    destination = resolve_path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cli = _cli()
    cmd = [
        str(cli), "pcb", "export", "pos",
        "--output", str(destination),
        "--side", side,
        "--format", "csv",
        "--units", units,
        str(path),
    ]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=180)
    return {
        "ok": completed.returncode == 0 and destination.exists(),
        "kind": "pos",
        "board": str(path),
        "output": str(destination),
        "exists": destination.exists(),
        "bytes": destination.stat().st_size if destination.exists() else 0,
        "side": side,
        "units": units,
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
    }


def export_netlist(schematic: str | Path, output_file: str | Path, format: str = "kicadsexpr") -> dict[str, Any]:
    path = resolve_path(schematic, ".kicad_sch")
    destination = resolve_path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cli = _cli()
    cmd = [str(cli), "sch", "export", "netlist", "--format", format, "--output", str(destination), str(path)]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=180)
    return {
        "ok": completed.returncode == 0 and destination.exists(),
        "kind": "netlist",
        "format": format,
        "schematic": str(path),
        "output": str(destination),
        "exists": destination.exists(),
        "bytes": destination.stat().st_size if destination.exists() else 0,
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
    }


def export_pdf_schematic(schematic: str | Path, output_file: str | Path) -> dict[str, Any]:
    path = resolve_path(schematic, ".kicad_sch")
    destination = resolve_path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cli = _cli()
    cmd = [str(cli), "sch", "export", "pdf", "--output", str(destination), str(path)]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=180)
    return {
        "ok": completed.returncode == 0 and destination.exists(),
        "kind": "pdf_schematic",
        "schematic": str(path),
        "output": str(destination),
        "exists": destination.exists(),
        "bytes": destination.stat().st_size if destination.exists() else 0,
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
    }


def create_release_package(project: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Build a fab package: review JSON + gerbers + drill + pos + bom + ipc2581 when possible."""
    info = project_info(project)
    out = resolve_path(output_directory)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project": info,
        "stamp": stamp,
        "artifacts": {},
        "ok": True,
    }
    review = review_project(info["path"])
    review_path = out / "kiclaw-review.json"
    review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    manifest["artifacts"]["review"] = str(review_path)
    manifest["review_ok"] = review.get("ok")

    for board in info["boards"]:
        board_name = Path(board).stem
        gerbers = run_export("gerbers", board, out / f"{board_name}-gerbers")
        drill = run_export("drill", board, out / f"{board_name}-drill")
        ipc = run_export("ipc2581", board, out / f"{board_name}.xml")
        pos = export_pos(board, out / f"{board_name}-pos.csv", units="mm")
        manifest["artifacts"][board_name] = {
            "gerbers": gerbers,
            "drill": drill,
            "ipc2581": ipc,
            "pos": pos,
        }
        if not all(item.get("ok") for item in (gerbers, drill, ipc, pos)):
            manifest["ok"] = False

    for schematic in info["schematics"]:
        sch_name = Path(schematic).stem
        bom = export_bom(schematic, out / f"{sch_name}-bom.csv")
        netlist = export_netlist(schematic, out / f"{sch_name}.net")
        manifest["artifacts"][f"sch-{sch_name}"] = {"bom": bom, "netlist": netlist}
        if not bom.get("ok") or not netlist.get("ok"):
            manifest["ok"] = False

    notes = out / "RELEASE_NOTES.txt"
    notes.write_text(
        "\n".join([
            f"KiClaw release package {stamp}",
            f"Project: {info['path']}",
            f"Review ok: {review.get('ok')}",
            f"Finding counts: {review.get('finding_counts')}",
            "Generated by create_release_package. Verify with manufacturing before fab.",
            "",
        ]),
        encoding="utf-8",
    )
    manifest["artifacts"]["notes"] = str(notes)
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
