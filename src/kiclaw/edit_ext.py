"""Additional guarded schematic/PCB mutations."""

from __future__ import annotations

import math
import re
import uuid
from pathlib import Path
from typing import Any

from .core import (
    KiClawError,
    begin_schematic_transaction,
    begin_transaction,
    board_summary,
    run_check,
    schematic_roundtrip_check,
    schematic_summary,
    _diff,
    _schematic_insert_before_sheet_instances,
    _schematic_symbol_forms,
    _top_level_forms,
    resolve_path,
)


def rotate_footprint(board: str | Path, reference: str, rotation: float, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set footprint rotation (degrees) with snapshot + DRC."""
    if not math.isfinite(rotation):
        raise KiClawError("rotation must be finite")
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    transaction = begin_transaction(path, "rotate_footprint", expected_sha256 or pre["sha256"])
    text = transaction.before_content
    forms = _top_level_forms(text, "footprint")
    selected = next((form for form in forms if f'(property "Reference" "{reference}"' in form), None)
    if selected is None:
        raise KiClawError(f"Footprint reference not found: {reference}")
    at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", selected)
    if at is None:
        raise KiClawError(f"Footprint {reference} has no editable position")
    x, y = at.group(1), at.group(2)
    new_at = f"(at {x} {y} {rotation})"
    snapshot = transaction.take_snapshot("before-rotate-footprint")
    content = text.replace(selected, selected.replace(at.group(0), new_at, 1), 1)
    after = transaction.commit(content)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "reference": reference,
        "rotation": rotation,
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
    }


def add_via(
    board: str | Path,
    net_name: str,
    x: float,
    y: float,
    size: float = 0.8,
    drill: float = 0.4,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if not all(math.isfinite(v) for v in (x, y, size, drill)) or size <= 0 or drill <= 0:
        raise KiClawError("via geometry must be finite and positive")
    path = resolve_path(board, ".kicad_pcb")
    before = board_summary(path)
    matching = [net for net in before["nets"] if net["name"] == net_name]
    if not matching or matching[0]["id"] == 0:
        raise KiClawError(f"A non-empty net named {net_name!r} was not found")
    transaction = begin_transaction(path, "add_via", expected_sha256 or before["sha256"])
    snapshot = transaction.take_snapshot("before-add-via")
    via = f'\n\t(via (at {x} {y}) (size {size}) (drill {drill}) (layers "F.Cu" "B.Cu") (net {matching[0]["id"]}))\n'
    text = transaction.before_content
    final = text.rfind(")")
    if final < 0:
        raise KiClawError("Board is not a valid S-expression")
    content = text[:final] + via + text[final:]
    after = transaction.commit(content, lambda value: _assert_stat(transaction.before_summary, value, "vias", 1))
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "via": {"net": net_name, "at": [x, y], "size": size, "drill": drill},
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
    }


def _assert_stat(before: dict[str, Any], after: dict[str, Any], key: str, delta: int) -> None:
    if after["statistics"].get(key) != before["statistics"].get(key, 0) + delta:
        raise KiClawError(f"Post-write verification failed: expected {key} to change by {delta}")


def delete_footprint(board: str | Path, reference: str, expected_sha256: str | None = None) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    transaction = begin_transaction(path, "delete_footprint", expected_sha256 or pre["sha256"])
    text = transaction.before_content
    forms = _top_level_forms(text, "footprint")
    selected = next((form for form in forms if f'(property "Reference" "{reference}"' in form), None)
    if selected is None:
        raise KiClawError(f"Footprint reference not found: {reference}")
    snapshot = transaction.take_snapshot("before-delete-footprint")
    # remove form and following whitespace carefully
    idx = text.find(selected)
    content = text[:idx] + text[idx + len(selected) :]
    content = re.sub(r"\n{3,}", "\n\n", content)
    after = transaction.commit(content, lambda value: _assert_stat(transaction.before_summary, value, "footprints", -1))
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "deleted": reference,
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
    }


def set_footprint_property(
    board: str | Path,
    reference: str,
    property_name: str,
    value: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if property_name not in {"Value", "Reference", "Footprint", "Datasheet", "Description"}:
        raise KiClawError("property_name must be one of Value/Reference/Footprint/Datasheet/Description")
    if property_name == "Reference" and not value:
        raise KiClawError("Reference cannot be empty")
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    transaction = begin_transaction(path, "set_footprint_property", expected_sha256 or pre["sha256"])
    text = transaction.before_content
    forms = _top_level_forms(text, "footprint")
    selected = next((form for form in forms if f'(property "Reference" "{reference}"' in form), None)
    if selected is None:
        raise KiClawError(f"Footprint reference not found: {reference}")
    pattern = rf'(\(property "{re.escape(property_name)}" ")[^"]*(")'
    if not re.search(pattern, selected):
        raise KiClawError(f"Property {property_name} not found on footprint {reference}")
    updated = re.sub(pattern, rf"\g<1>{value}\g<2>", selected, count=1)
    snapshot = transaction.take_snapshot("before-set-footprint-property")
    content = text.replace(selected, updated, 1)
    after = transaction.commit(content)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "reference": reference,
        "property": property_name,
        "value": value,
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
    }


def add_net_label(
    schematic: str | Path,
    name: str,
    x: float,
    y: float,
    rotation: float = 0.0,
    kind: str = "label",
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Add a local label (kind=label) or global_label."""
    if kind not in {"label", "global_label"}:
        raise KiClawError("kind must be label or global_label")
    if not name or not all(math.isfinite(v) for v in (x, y, rotation)):
        raise KiClawError("name required; coordinates must be finite")
    transaction = begin_schematic_transaction(schematic, "add_net_label", expected_sha256)
    before = transaction.before_summary
    snapshot = transaction.take_snapshot("before-add-net-label")
    text = transaction.before_content
    insertion = _schematic_insert_before_sheet_instances(text)
    form = (
        f'\t({kind}\n'
        f'\t\t(at {format(x, ".12g")} {format(y, ".12g")} {format(rotation, ".12g")})\n'
        f'\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n'
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t\t"{name}"\n'
        f'\t)\n'
    )
    # KiCad 9/10 often use (label "NAME" (at ...) ...) — try modern form
    form = (
        f'\t({kind} "{name}"\n'
        f'\t\t(at {format(x, ".12g")} {format(y, ".12g")} {format(rotation, ".12g")})\n'
        f'\t\t(effects\n'
        f'\t\t\t(font\n'
        f'\t\t\t\t(size 1.27 1.27)\n'
        f'\t\t\t)\n'
        f'\t\t\t(justify left bottom)\n'
        f'\t\t)\n'
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t)\n'
    )
    content = text[:insertion] + form + text[insertion:]

    def verify(after: dict[str, Any]) -> None:
        key = kind
        if after["top_level_counts"].get(key, 0) != before["top_level_counts"].get(key, 0) + 1:
            raise KiClawError(f"Post-write verification failed for {kind} count")
        if not schematic_roundtrip_check(transaction.schematic)["ok"]:
            raise KiClawError("Post-write schematic round-trip verification failed")

    after = transaction.commit(content, verify)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "label": {"name": name, "kind": kind, "at": [x, y], "rotation": rotation},
        "diff": {
            "sha256": {"before": before["sha256"], "after": after["sha256"]},
            "top_level_counts": {kind: after["top_level_counts"].get(kind, 0) - before["top_level_counts"].get(kind, 0)},
        },
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": run_check("erc", transaction.schematic)},
    }


def set_component_value(
    schematic: str | Path,
    reference: str,
    value: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    transaction = begin_schematic_transaction(schematic, "set_component_value", expected_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    symbols = _schematic_symbol_forms(text)
    selected = next((form for form in symbols if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', form)), None)
    if selected is None:
        raise KiClawError(f"Component reference not found: {reference}")
    if not re.search(r'\(property\s+"Value"\s+"', selected):
        raise KiClawError(f"Component {reference} has no Value property")
    updated = re.sub(r'(\(property\s+"Value"\s+")[^"]*(")', rf"\g<1>{value}\g<2>", selected, count=1)
    snapshot = transaction.take_snapshot("before-set-component-value")
    content = text.replace(selected, updated, 1)
    after = transaction.commit(content, lambda _: None if schematic_roundtrip_check(transaction.schematic)["ok"] else (_ for _ in ()).throw(KiClawError("round-trip failed")))
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "reference": reference,
        "value": value,
        "diff": {"sha256": {"before": before["sha256"], "after": after["sha256"]}},
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": run_check("erc", transaction.schematic)},
    }


def move_component(
    schematic: str | Path,
    reference: str,
    x: float,
    y: float,
    rotation: float | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if not all(math.isfinite(v) for v in (x, y)) or (rotation is not None and not math.isfinite(rotation)):
        raise KiClawError("placement values must be finite")
    transaction = begin_schematic_transaction(schematic, "move_component", expected_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    symbols = _schematic_symbol_forms(text)
    selected = next((form for form in symbols if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', form)), None)
    if selected is None:
        raise KiClawError(f"Component reference not found: {reference}")
    at = re.search(r"\(at\s+-?[\d.]+\s+-?[\d.]+(?:\s+-?[\d.]+)?\)", selected)
    if at is None:
        raise KiClawError("Component has no placement")
    parts = at.group(0).removeprefix("(at").removesuffix(")").split()
    angle = rotation if rotation is not None else (float(parts[2]) if len(parts) == 3 else 0.0)
    new_at = f"(at {format(x, '.12g')} {format(y, '.12g')} {format(angle, '.12g')})"
    snapshot = transaction.take_snapshot("before-move-component")
    content = text.replace(selected, selected.replace(at.group(0), new_at, 1), 1)
    after = transaction.commit(content)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "reference": reference,
        "at": [x, y, angle],
        "diff": {"sha256": {"before": before["sha256"], "after": after["sha256"]}},
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": run_check("erc", transaction.schematic)},
    }


def place_power_symbol(
    schematic: str | Path,
    power_name: str,
    x: float,
    y: float,
    reference: str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Place a power flag by cloning power:GND / power:+3V3 style instances when present."""
    lib_id = power_name if ":" in power_name else f"power:{power_name}"
    ref = reference or f"#PWR{uuid.uuid4().hex[:4].upper()}"
    from .core import add_component
    return add_component(schematic, lib_id, ref, x, y, power_name.split(":")[-1], 0.0, expected_sha256)


def rotate_component(
    schematic: str | Path,
    reference: str,
    rotation: float,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if not math.isfinite(rotation):
        raise KiClawError("rotation must be finite")
    transaction = begin_schematic_transaction(schematic, "rotate_component", expected_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    symbols = _schematic_symbol_forms(text)
    selected = next((form for form in symbols if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', form)), None)
    if selected is None:
        raise KiClawError(f"Component reference not found: {reference}")
    at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", selected)
    if at is None:
        raise KiClawError("Component has no placement")
    x, y = at.group(1), at.group(2)
    new_at = f"(at {x} {y} {format(rotation, '.12g')})"
    snapshot = transaction.take_snapshot("before-rotate-component")
    content = text.replace(selected, selected.replace(at.group(0), new_at, 1), 1)
    after = transaction.commit(content)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "reference": reference,
        "rotation": rotation,
        "diff": {"sha256": {"before": before["sha256"], "after": after["sha256"]}},
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": run_check("erc", transaction.schematic)},
    }


def delete_component(schematic: str | Path, reference: str, expected_sha256: str | None = None) -> dict[str, Any]:
    transaction = begin_schematic_transaction(schematic, "delete_component", expected_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    symbols = _schematic_symbol_forms(text)
    selected = next((form for form in symbols if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', form)), None)
    if selected is None:
        raise KiClawError(f"Component reference not found: {reference}")
    snapshot = transaction.take_snapshot("before-delete-component")
    content = text.replace(selected, "", 1)
    content = re.sub(r"\n{3,}", "\n\n", content)

    def verify(after: dict[str, Any]) -> None:
        if after["top_level_counts"].get("symbol", 0) != before["top_level_counts"].get("symbol", 0) - 1:
            raise KiClawError("Post-write verification failed: symbol count did not decrease by 1")
        if not schematic_roundtrip_check(transaction.schematic)["ok"]:
            raise KiClawError("round-trip failed")

    after = transaction.commit(content, verify)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "deleted": reference,
        "diff": {
            "sha256": {"before": before["sha256"], "after": after["sha256"]},
            "top_level_counts": {"symbol": -1},
        },
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": run_check("erc", transaction.schematic)},
        "note": "Wires attached to the deleted symbol are not auto-cleaned.",
    }


def delete_wire(
    schematic: str | Path,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    tolerance: float = 0.01,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    transaction = begin_schematic_transaction(schematic, "delete_wire", expected_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    wires = _top_level_forms(text, "wire")
    target = None
    for form in wires:
        pts = re.findall(r"\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        if len(pts) < 2:
            continue
        pairs = [(float(a), float(b)) for a, b in pts]
        if _points_match(pairs[0], (start_x, start_y), tolerance) and _points_match(pairs[1], (end_x, end_y), tolerance):
            target = form
            break
        if _points_match(pairs[0], (end_x, end_y), tolerance) and _points_match(pairs[1], (start_x, start_y), tolerance):
            target = form
            break
    if target is None:
        raise KiClawError("No wire found matching the given endpoints")
    snapshot = transaction.take_snapshot("before-delete-wire")
    content = text.replace(target, "", 1)
    content = re.sub(r"\n{3,}", "\n\n", content)

    def verify(after: dict[str, Any]) -> None:
        if after["top_level_counts"].get("wire", 0) != before["top_level_counts"].get("wire", 0) - 1:
            raise KiClawError("Post-write verification failed: wire count")

    after = transaction.commit(content, verify)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "deleted": {"start": [start_x, start_y], "end": [end_x, end_y]},
        "diff": {"sha256": {"before": before["sha256"], "after": after["sha256"]}, "top_level_counts": {"wire": -1}},
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": run_check("erc", transaction.schematic)},
    }


def _points_match(a: tuple[float, float], b: tuple[float, float], tol: float) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def delete_track(
    board: str | Path,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    tolerance: float = 0.01,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    transaction = begin_transaction(path, "delete_track", expected_sha256 or pre["sha256"])
    text = transaction.before_content
    target = None
    for form in _top_level_forms(text, "segment"):
        start = re.search(r"\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        end = re.search(r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        if not start or not end:
            continue
        s = (float(start.group(1)), float(start.group(2)))
        e = (float(end.group(1)), float(end.group(2)))
        if (_points_match(s, (start_x, start_y), tolerance) and _points_match(e, (end_x, end_y), tolerance)) or (
            _points_match(s, (end_x, end_y), tolerance) and _points_match(e, (start_x, start_y), tolerance)
        ):
            target = form
            break
    if target is None:
        raise KiClawError("No track segment found matching the given endpoints")
    snapshot = transaction.take_snapshot("before-delete-track")
    content = text.replace(target, "", 1)
    after = transaction.commit(content, lambda value: _assert_stat(transaction.before_summary, value, "tracks", -1))
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "deleted": {"start": [start_x, start_y], "end": [end_x, end_y]},
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
    }


def delete_via(
    board: str | Path,
    x: float,
    y: float,
    tolerance: float = 0.05,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    transaction = begin_transaction(path, "delete_via", expected_sha256 or pre["sha256"])
    text = transaction.before_content
    target = None
    for form in _top_level_forms(text, "via"):
        at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        if at and _points_match((float(at.group(1)), float(at.group(2))), (x, y), tolerance):
            target = form
            break
    if target is None:
        raise KiClawError("No via found at the given coordinates")
    snapshot = transaction.take_snapshot("before-delete-via")
    content = text.replace(target, "", 1)
    after = transaction.commit(content, lambda value: _assert_stat(transaction.before_summary, value, "vias", -1))
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "deleted": {"at": [x, y]},
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
    }


def place_footprint(
    board: str | Path,
    source_reference: str,
    new_reference: str,
    x: float,
    y: float,
    rotation: float = 0.0,
    value: str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Clone an existing footprint instance to a new reference/placement (safe, no free library invent)."""
    if not all(math.isfinite(v) for v in (x, y, rotation)):
        raise KiClawError("placement must be finite")
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    if any(fp["reference"] == new_reference for fp in pre["footprints"]):
        raise KiClawError(f"Reference already exists: {new_reference}")
    transaction = begin_transaction(path, "place_footprint", expected_sha256 or pre["sha256"])
    text = transaction.before_content
    forms = _top_level_forms(text, "footprint")
    template = next((form for form in forms if f'(property "Reference" "{source_reference}"' in form), None)
    if template is None:
        raise KiClawError(f"Source footprint not found: {source_reference}")
    at = re.search(r"\(at\s+-?[\d.]+\s+-?[\d.]+(?:\s+-?[\d.]+)?\)", template)
    if at is None:
        raise KiClawError("Template has no placement")
    clone = template.replace(at.group(0), f"(at {x} {y} {rotation})", 1)
    clone = re.sub(r'(\(property "Reference" ")[^"]*(")', rf"\g<1>{new_reference}\g<2>", clone, count=1)
    if value is not None:
        clone = re.sub(r'(\(property "Value" ")[^"]*(")', rf"\g<1>{value}\g<2>", clone, count=1)
    uuid_map: dict[str, str] = {}

    def repl_uuid(match: re.Match[str]) -> str:
        old = match.group(1)
        uuid_map.setdefault(old, str(uuid.uuid4()))
        return f'(uuid "{uuid_map[old]}")'

    clone = re.sub(r'\(uuid\s+"([^"]+)"\)', repl_uuid, clone)
    snapshot = transaction.take_snapshot("before-place-footprint")
    final = text.rfind(")")
    content = text[:final] + "\n" + clone + "\n" + text[final:]
    after = transaction.commit(content, lambda value: _assert_stat(transaction.before_summary, value, "footprints", 1))
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "source_reference": source_reference,
        "reference": new_reference,
        "at": [x, y, rotation],
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
        "limitation": "Clones an existing board footprint; free library placement without a template is not enabled.",
    }


def create_zone(
    board: str | Path,
    net_name: str,
    points: list[list[float]],
    layer: str = "F.Cu",
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Insert a simple copper zone polygon (fill still needs KiCad fill operation)."""
    if len(points) < 3:
        raise KiClawError("zone needs at least 3 points")
    if not all(math.isfinite(c) for pt in points for c in pt[:2]):
        raise KiClawError("zone points must be finite")
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    matching = [net for net in pre["nets"] if net["name"] == net_name]
    if not matching:
        raise KiClawError(f"Net not found: {net_name}")
    net_id = matching[0]["id"]
    transaction = begin_transaction(path, "create_zone", expected_sha256 or pre["sha256"])
    snapshot = transaction.take_snapshot("before-create-zone")
    pts = " ".join(f"(xy {p[0]} {p[1]})" for p in points)
    zone = (
        f'\n\t(zone (net {net_id}) (net_name "{net_name}") (layer "{layer}") (hatch edge 0.5)\n'
        f'\t\t(connect_pads (clearance 0.5))\n'
        f'\t\t(min_thickness 0.25)\n'
        f'\t\t(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
        f'\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{pts}\n\t\t\t)\n\t\t)\n'
        f'\t)\n'
    )
    text = transaction.before_content
    final = text.rfind(")")
    content = text[:final] + zone + text[final:]
    after = transaction.commit(content, lambda value: _assert_stat(transaction.before_summary, value, "zones", 1))
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "zone": {"net": net_name, "layer": layer, "points": points},
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
        "note": "Zone geometry inserted; run fill_zones in KiCad for copper pour fill if needed.",
    }


def dry_run_edit(operation: str, **kwargs: Any) -> dict[str, Any]:
    """Validate arguments and describe an edit without applying it."""
    known = {
        "add_track", "add_via", "move_footprint", "rotate_footprint", "delete_track", "delete_via",
        "delete_footprint", "place_footprint", "add_wire", "delete_wire", "add_component", "delete_component",
        "move_component", "set_component_value", "add_net_label", "create_zone",
    }
    if operation not in known:
        return {"ok": False, "operation": operation, "reason": f"Unknown operation; known={sorted(known)}"}
    return {
        "ok": True,
        "dry_run": True,
        "operation": operation,
        "arguments": kwargs,
        "would_apply": True,
        "note": "Dry-run does not mutate files. Call the real tool to apply with snapshots.",
    }


def generate_assembly_notes(project: str | Path) -> dict[str, Any]:
    """Generate basic assembly notes from project contents."""
    from .core import project_info
    from .inspect_ext import list_components

    info = project_info(project)
    lines = [
        "# Assembly notes (KiClaw generated)",
        f"Project: {info['path']}",
        "",
        "## Boards",
        *[f"- {b}" for b in info["boards"]],
        "",
        "## Schematics / component counts",
    ]
    total = 0
    for sch in info["schematics"]:
        try:
            comps = list_components(sch)
            total += comps["count"]
            lines.append(f"- {sch}: {comps['count']} components")
            for c in comps["components"][:30]:
                lines.append(f"  - {c.get('reference')}: {c.get('value')} ({c.get('lib_id')})")
        except Exception as exc:
            lines.append(f"- {sch}: error {exc}")
    lines += ["", f"Total listed components: {total}", "", "Verify orientation, polarity, and DNP flags before assembly."]
    text = "\n".join(lines) + "\n"
    return {"ok": True, "project": info["path"], "notes": text, "component_count": total}


def validate_design_rules(board: str | Path) -> dict[str, Any]:
    """Consistency checks between design-rule hints and actual geometry."""
    from .inspect_ext import get_design_rules
    from .core import run_dfm

    rules = get_design_rules(board)
    dfm = run_dfm(board)
    return {
        "ok": dfm.get("ok", False),
        "rules": rules,
        "dfm": {"ok": dfm.get("ok"), "finding_counts": dfm.get("finding_counts"), "findings": dfm.get("findings")},
        "note": "Combines file-parsed rule hints with deterministic DFM; not a full custom-rule engine.",
    }


def fill_zones(board: str | Path) -> dict[str, Any]:
    """Zone fill requires native KiCad UI/plugin; report honest limitation."""
    return {
        "ok": False,
        "board": str(resolve_path(board, ".kicad_pcb")),
        "reason": "Zone fill is not exposed as a stable headless CLI operation in this KiCad version. Open PCB Editor and run Fill All Zones, or use a future IPC action.",
        "planned": True,
    }


def lock_footprint(board: str | Path, reference: str, locked: bool = True, expected_sha256: str | None = None) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    pre = board_summary(path)
    transaction = begin_transaction(path, "lock_footprint", expected_sha256 or pre["sha256"])
    text = transaction.before_content
    forms = _top_level_forms(text, "footprint")
    selected = next((form for form in forms if f'(property "Reference" "{reference}"' in form), None)
    if selected is None:
        raise KiClawError(f"Footprint not found: {reference}")
    if locked and "(locked yes)" not in selected and " locked" not in selected[:80]:
        # insert locked after opening footprint line
        updated = re.sub(r"(\(footprint\s+[^\n]+)", r"\1\n\t\t(locked yes)", selected, count=1)
    elif not locked:
        updated = selected.replace("(locked yes)", "").replace("(locked)", "")
    else:
        updated = selected
    snapshot = transaction.take_snapshot("before-lock-footprint")
    content = text.replace(selected, updated, 1)
    after = transaction.commit(content)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "reference": reference,
        "locked": locked,
        "diff": _diff(transaction.before_summary, after),
        "verification": run_check("drc", path),
    }


def unlock_footprint(board: str | Path, reference: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return lock_footprint(board, reference, locked=False, expected_sha256=expected_sha256)

