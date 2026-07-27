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
