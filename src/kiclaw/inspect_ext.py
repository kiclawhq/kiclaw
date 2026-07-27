"""Rich project inspection tools (read-only, file-first)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .analysis import build_analysis_context, classify_net_name
from .core import KiClawError, board_summary, project_info, resolve_path, run_check, schematic_summary, _top_level_forms


def list_project_files(project: str | Path) -> dict[str, Any]:
    """List KiCad and library files under a project directory."""
    info = project_info(project)
    root = Path(info["path"])
    patterns = {
        "boards": "*.kicad_pcb",
        "schematics": "*.kicad_sch",
        "projects": "*.kicad_pro",
        "symbols": "*.kicad_sym",
        "footprints": "*.kicad_mod",
        "tables": "*-lib-table",
        "worksheets": "*.kicad_wks",
        "netlists": "*.net",
    }
    files: dict[str, list[str]] = {}
    for key, pattern in patterns.items():
        found = sorted({str(p) for p in root.rglob(pattern) if p.is_file() and ".kiclaw" not in p.parts})
        files[key] = found
    pretty = sorted({str(p) for p in root.rglob("*.pretty") if p.is_dir()})
    return {"ok": True, "path": str(root), "files": files, "footprint_libraries": pretty, "counts": {k: len(v) for k, v in files.items()}}


def get_project_structure(project: str | Path) -> dict[str, Any]:
    """Hierarchical summary of boards, schematics, and sheet metadata."""
    info = project_info(project)
    boards = []
    for board in info["boards"]:
        try:
            summary = board_summary(board)
            boards.append({
                "path": board,
                "sha256": summary["sha256"],
                "statistics": summary["statistics"],
                "approximate": True,
            })
        except KiClawError as exc:
            boards.append({"path": board, "error": str(exc)})
    schematics = []
    for sch in info["schematics"]:
        try:
            summary = schematic_summary(sch)
            schematics.append({
                "path": sch,
                "sha256": summary["sha256"],
                "version": summary.get("version"),
                "uuid": summary.get("uuid"),
                "top_level_counts": summary.get("top_level_counts"),
            })
        except KiClawError as exc:
            schematics.append({"path": sch, "error": str(exc)})
    return {
        "ok": True,
        "path": info["path"],
        "project_files": info["project_files"],
        "boards": boards,
        "schematics": schematics,
        "note": "Sheet hierarchy is limited to top-level kicad_sch files; nested sheet graph expansion is partial.",
    }


def list_components(schematic: str | Path) -> dict[str, Any]:
    """List schematic symbol instances with reference/value/lib_id/placement."""
    path = resolve_path(schematic, ".kicad_sch")
    text = path.read_text(encoding="utf-8")
    components = []
    for form in _top_level_forms(text, "symbol"):
        if re.match(r'\(symbol\s+"', form.strip()):
            continue  # library definition, not instance
        ref = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', form)
        value = re.search(r'\(property\s+"Value"\s+"([^"]*)"', form)
        lib = re.search(r'\(lib_id\s+"([^"]*)"\)', form)
        at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", form)
        footprint = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', form)
        components.append({
            "reference": ref.group(1) if ref else None,
            "value": value.group(1) if value else None,
            "lib_id": lib.group(1) if lib else None,
            "footprint": footprint.group(1) if footprint else None,
            "at": [float(x) for x in at.groups(default="0")[:3]] if at else None,
        })
    return {"ok": True, "path": str(path), "count": len(components), "components": components, "approximate": False}


def get_component_details(schematic: str | Path, reference: str) -> dict[str, Any]:
    path = resolve_path(schematic, ".kicad_sch")
    text = path.read_text(encoding="utf-8")
    for form in _top_level_forms(text, "symbol"):
        if re.match(r'\(symbol\s+"', form.strip()):
            continue
        ref = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', form)
        if not ref or ref.group(1) != reference:
            continue
        props = {m.group(1): m.group(2) for m in re.finditer(r'\(property\s+"([^"]+)"\s+"([^"]*)"', form)}
        lib = re.search(r'\(lib_id\s+"([^"]*)"\)', form)
        at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", form)
        uuid = re.search(r'\(uuid\s+"([^"]+)"\)', form)
        return {
            "ok": True,
            "path": str(path),
            "reference": reference,
            "lib_id": lib.group(1) if lib else None,
            "properties": props,
            "at": [float(x) for x in at.groups(default="0")[:3]] if at else None,
            "uuid": uuid.group(1) if uuid else None,
        }
    raise KiClawError(f"Component reference not found: {reference}")


def get_footprint_details(board: str | Path, reference: str) -> dict[str, Any]:
    ctx = build_analysis_context(board)
    for fp in ctx.footprints:
        if fp.reference == reference:
            return {
                "ok": True,
                "path": str(ctx.path),
                "reference": fp.reference,
                "value": fp.value,
                "at": fp.at,
                "net_ids": sorted(fp.net_ids),
                "net_names": sorted(fp.net_names),
                "pads": [
                    {"number": p.number, "net_id": p.net_id, "net_name": p.net_name, "at": p.at}
                    for p in fp.pads
                ],
                "approximate": True,
            }
    raise KiClawError(f"Footprint reference not found: {reference}")


def get_net_details(board: str | Path, net_name: str) -> dict[str, Any]:
    ctx = build_analysis_context(board)
    net = next((n for n in ctx.nets if str(n.get("name")) == net_name), None)
    if net is None:
        raise KiClawError(f"Net not found: {net_name}")
    net_id = int(net["id"])
    attachments = []
    for fp in ctx.footprints:
        for pad in fp.pads:
            if pad.net_id == net_id:
                attachments.append({
                    "reference": fp.reference,
                    "value": fp.value,
                    "pad": pad.number,
                    "net_name": pad.net_name,
                })
    return {
        "ok": True,
        "path": str(ctx.path),
        "net": {"id": net_id, "name": net_name, "tags": sorted(classify_net_name(net_name))},
        "attachments": attachments,
        "segment_count": ctx.segments_by_net.get(net_id, 0),
        "via_count": ctx.vias_by_net.get(net_id, 0),
        "zone_count": sum(1 for z in ctx.zones if z.net_id == net_id),
        "approximate": True,
    }


def get_layer_stack(board: str | Path) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    text = path.read_text(encoding="utf-8")
    layers = []
    for match in re.finditer(r'\(\s*(\d+)\s+"([^"]+)"\s+([^\s)]+)(?:\s+"([^"]*)")?', text):
        # crude: only inside layers block — filter known layer types
        if match.group(3) in {"signal", "user", "power", "jumper", "mixed"} or match.group(2).endswith((".Cu", ".SilkS", ".Mask", ".Paste", ".Adhes", ".CrtYd", ".Fab")) or match.group(2) in {"Edge.Cuts", "Margin", "Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User"}:
            layers.append({
                "ordinal": int(match.group(1)),
                "name": match.group(2),
                "type": match.group(3),
                "user_name": match.group(4),
            })
    # de-dupe by name preserving order
    seen: set[str] = set()
    unique = []
    for layer in layers:
        if layer["name"] in seen:
            continue
        seen.add(layer["name"])
        unique.append(layer)
    copper = [layer for layer in unique if layer["name"].endswith(".Cu") or layer["type"] == "signal"]
    return {
        "ok": True,
        "path": str(path),
        "layers": unique,
        "copper_layer_count": len(copper),
        "approximate": True,
        "note": "Parsed from board layers block; not a full stackup dielectric model.",
    }


def get_design_rules(board: str | Path) -> dict[str, Any]:
    """Extract conservative design-rule hints from board setup / net classes if present."""
    path = resolve_path(board, ".kicad_pcb")
    text = path.read_text(encoding="utf-8")
    setup_forms = _top_level_forms(text, "setup")
    setup_text = setup_forms[0] if setup_forms else ""
    thickness = re.search(r"\(thickness\s+([\d.]+)\)", text)
    clearances = re.findall(r"\(clearance\s+([\d.]+)\)", setup_text or text)
    track_widths = re.findall(r"\(trace_width\s+([\d.]+)\)", text)
    via_sizes = re.findall(r"\(via_size\s+([\d.]+)\)", text)
    via_drills = re.findall(r"\(via_drill\s+([\d.]+)\)", text)
    return {
        "ok": True,
        "path": str(path),
        "board_thickness_mm": float(thickness.group(1)) if thickness else None,
        "clearances_mm": [float(x) for x in clearances[:20]],
        "trace_widths_mm": sorted({float(x) for x in track_widths})[:20],
        "via_sizes_mm": sorted({float(x) for x in via_sizes})[:20],
        "via_drills_mm": sorted({float(x) for x in via_drills})[:20],
        "approximate": True,
        "note": "File-parsed hints only; full custom rule tables may require native KiCad UI export.",
    }


def find_objects(project_or_file: str | Path, query: str, kinds: list[str] | None = None) -> dict[str, Any]:
    """Search components/nets/footprints by substring (case-insensitive)."""
    needle = query.strip().lower()
    if not needle:
        raise KiClawError("query must not be empty")
    kinds = kinds or ["component", "footprint", "net"]
    path = resolve_path(project_or_file)
    matches: list[dict[str, Any]] = []
    if path.is_dir() or path.suffix == ".kicad_pro":
        info = project_info(path)
        boards = info["boards"]
        schematics = info["schematics"]
    elif path.suffix == ".kicad_pcb":
        boards, schematics = [str(path)], []
    elif path.suffix == ".kicad_sch":
        boards, schematics = [], [str(path)]
    else:
        info = project_info(path.parent if path.is_file() else path)
        boards, schematics = info["boards"], info["schematics"]

    if "footprint" in kinds or "net" in kinds:
        for board in boards:
            summary = board_summary(board)
            if "footprint" in kinds:
                for fp in summary["footprints"]:
                    blob = f"{fp.get('reference')} {fp.get('value')}".lower()
                    if needle in blob:
                        matches.append({"kind": "footprint", "source": board, **fp})
            if "net" in kinds:
                for net in summary["nets"]:
                    if needle in str(net.get("name", "")).lower():
                        matches.append({"kind": "net", "source": board, **net})
    if "component" in kinds:
        for sch in schematics:
            for comp in list_components(sch)["components"]:
                blob = f"{comp.get('reference')} {comp.get('value')} {comp.get('lib_id')}".lower()
                if needle in blob:
                    matches.append({"kind": "component", "source": sch, **comp})
    return {"ok": True, "query": query, "kinds": kinds, "count": len(matches), "matches": matches[:200]}


def get_drc_errors(board: str | Path) -> dict[str, Any]:
    result = run_check("drc", board)
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    violations = report.get("violations", []) if isinstance(report, dict) else []
    unconnected = report.get("unconnected_items", []) if isinstance(report, dict) else []
    return {
        "ok": result.get("ok", False),
        "available": result.get("available", False),
        "exit_code": result.get("exit_code"),
        "violations": violations,
        "unconnected_items": unconnected,
        "counts": {"violations": len(violations), "unconnected": len(unconnected)},
        "raw": result,
    }


def get_erc_errors(schematic: str | Path) -> dict[str, Any]:
    result = run_check("erc", schematic)
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    sheets = report.get("sheets", []) if isinstance(report, dict) else []
    violations = []
    for sheet in sheets:
        if isinstance(sheet, dict):
            for item in sheet.get("violations", []) or []:
                violations.append({**item, "sheet": sheet.get("path")})
    # some versions put violations at top level
    if not violations and isinstance(report, dict):
        violations = list(report.get("violations", []) or [])
    return {
        "ok": result.get("ok", False),
        "available": result.get("available", False),
        "exit_code": result.get("exit_code"),
        "violations": violations,
        "counts": {"violations": len(violations)},
        "raw": result,
    }


def check_connectivity(board: str | Path, a: str, b: str) -> dict[str, Any]:
    """Check whether two footprint pads share a net (ref.pad or ref formats)."""
    ctx = build_analysis_context(board)

    def resolve(token: str) -> set[int]:
        token = token.strip()
        if "." in token:
            ref, pad = token.split(".", 1)
            nets: set[int] = set()
            for fp in ctx.footprints:
                if fp.reference == ref:
                    for p in fp.pads:
                        if p.number == pad and p.net_id is not None:
                            nets.add(p.net_id)
            return nets
        # footprint-level: all nets on that footprint
        for fp in ctx.footprints:
            if fp.reference == token:
                return set(fp.net_ids)
        # net name
        for net in ctx.nets:
            if str(net.get("name")) == token:
                return {int(net["id"])}
        return set()

    nets_a, nets_b = resolve(a), resolve(b)
    shared = sorted(nets_a & nets_b)
    net_by_id = {int(n["id"]): n.get("name") for n in ctx.nets}
    return {
        "ok": True,
        "a": a,
        "b": b,
        "connected": bool(shared),
        "shared_net_ids": shared,
        "shared_net_names": [net_by_id.get(i) for i in shared],
        "a_net_ids": sorted(nets_a),
        "b_net_ids": sorted(nets_b),
        "approximate": True,
        "note": "PCB pad-net graph only; does not prove schematic intent.",
    }


def get_transaction_history(board: str | Path, limit: int = 20) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    root = path.parent / ".kiclaw" / "transactions"
    if not root.is_dir():
        return {"ok": True, "board": str(path), "transactions": [], "count": 0}
    items = []
    for manifest in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, min(limit, 100))]:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("board") == str(path) or data.get("schematic") == str(path):
            items.append(data)
        elif "board" not in data and "schematic" not in data:
            items.append(data)
    # also include any for this board by path match softer
    if not items:
        for manifest in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if str(path) in json.dumps(data):
                items.append(data)
    return {"ok": True, "board": str(path), "transactions": items[:limit], "count": len(items[:limit])}
