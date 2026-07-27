"""Deterministic deep analysis packs for KiCad boards.

These packs parse board S-expressions only. They never invent electrical truth:
findings are structural, name-based, and proximity-based triage with explicit
evidence, confidence, and disclaimers. Native DRC/ERC remain the verification
source of truth.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .core import (
    KiClawError,
    _finding,
    _finding_counts,
    _top_level_forms,
    board_summary,
    resolve_path,
)

ANALYSIS_EVIDENCE = "KiClaw deep analysis over KiCad board S-expressions"
ANALYSIS_DISCLAIMER = (
    "Deep analysis is deterministic file-structure triage. It does not replace "
    "schematic review, datasheet checks, DRC/ERC, stackup/SI simulation, EMC lab "
    "testing, or engineering sign-off."
)

DEFAULT_PACKS: tuple[str, ...] = (
    "power_tree",
    "decoupling",
    "protection",
    "net_clusters",
    "ground",
    "connectivity",
)

_POWER_EXACT = {
    "VCC", "VDD", "VSS", "VEE", "VBUS", "VIN", "VOUT", "VBAT", "VSYS", "VRAW",
    "VCORE", "VIO", "AVDD", "DVDD", "AVCC", "DVCC", "IOVDD", "VDDA", "VDDIO",
    "3V3", "3.3V", "+3V3", "3V3A", "5V", "+5V", "12V", "+12V", "1V8", "+1V8",
    "1V2", "+1V2", "1V0", "+1V0", "2V5", "+2V5",
}
_GROUND_EXACT = {"GND", "AGND", "DGND", "PGND", "CGND", "SGND", "EARTH", "GROUND", "0V"}

_PROTECTION_VALUE = re.compile(
    r"(?i)\b(tvs|esd|pesd|usblc|nup\d|smb[aj]|smaj|smbj|varistor|mov|gdt|polyfuse|pptc|resettable\s*fuse)\b"
)
_CONNECTOR_VALUE = re.compile(
    r"(?i)\b(connector|usb|hdmi|rj-?45|ethernet|terminal|header|barrel|jack|socket|pogo|edge\s*card)\b"
)
_REGULATOR_VALUE = re.compile(
    r"(?i)\b(regulator|ldo|buck|boost|dcdc|dc-?dc|pmic|converter|tps\d|lm\d{3}|mp\d{4}|ams1117|ap2112)\b"
)
_CAP_VALUE = re.compile(r"(?i)(\d+(\.\d+)?\s*(p|n|u|µ|m)?f\b|cap(acitor)?|\d+(\.\d+)?u)")
_FUSE_VALUE = re.compile(r"(?i)\b(fuse|polyfuse|pptc|ptc)\b")


def _finite_positive(name: str, value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise KiClawError(f"{name} must be a positive finite number")
    return value


def classify_net_name(name: str) -> set[str]:
    """Return deterministic tags for a net name (conventions only)."""
    raw = (name or "").strip()
    if not raw:
        return set()
    upper = raw.upper().lstrip("/")
    tags: set[str] = set()
    if upper in _GROUND_EXACT or upper.endswith("_GND") or upper.startswith("GND") or upper.endswith("GND"):
        tags.add("ground")
    if upper in _POWER_EXACT or upper.startswith(("VDD", "VCC", "VBUS", "VBAT", "VIN", "VOUT", "VSYS", "VDDA", "VDDIO", "AVDD", "DVDD", "IOVDD")):
        tags.add("power")
    if re.match(r"^\+?\d+(\.\d+)?V", upper) or re.match(r"^\d+V\d+$", upper):
        tags.add("power")
    if re.search(r"(?i)(CLK|CLOCK|XTAL|OSC|MCLK|SCLK|BCLK)", upper):
        tags.add("clock")
    if re.search(r"(?i)(USB|DP|DM|D\+|D-|VBUS|CC1|CC2)", upper):
        tags.add("usb")
    if re.search(r"(?i)(SDA|SCL|I2C|TWI)", upper):
        tags.add("i2c")
    if re.search(r"(?i)(SPI|MOSI|MISO|SCK|SS|CS\d*)", upper):
        tags.add("spi")
    if re.search(r"(?i)(TX|RX|UART|USART|CTS|RTS)", upper):
        tags.add("uart")
    if re.search(r"(?i)(CAN[_H|_L]|CANH|CANL)", upper) or upper in {"CAN_H", "CAN_L"}:
        tags.add("can")
    if re.search(r"(?i)(LVDS|HDMI|PCIE|DDR|SERDES|DIFF)", upper) or upper.endswith(("_P", "_N", "+", "-")):
        tags.add("diff")
    if re.search(r"(?i)(ADC|AIN|AOUT|VREF|AGND|AUDIO|MIC)", upper):
        tags.add("analog")
    if not tags:
        tags.add("signal")
    return tags


def is_capacitor(ref: str | None, value: str | None) -> bool:
    ref_u = (ref or "").upper()
    # C1 / C12 — not CON1, CN1, CPU1
    if re.match(r"^C\d+", ref_u):
        return True
    return bool(value and _CAP_VALUE.search(value))


def is_connector(ref: str | None, value: str | None) -> bool:
    ref_u = (ref or "").upper()
    if re.match(r"^(J|P|CON|CN|USB|X)\d+", ref_u):
        return True
    return bool(value and _CONNECTOR_VALUE.search(value))


def is_protection(ref: str | None, value: str | None) -> bool:
    ref_u = (ref or "").upper()
    if re.match(r"^(TVS|ESD|D)\d+", ref_u) and value and _PROTECTION_VALUE.search(value):
        return True
    if value and _PROTECTION_VALUE.search(value):
        return True
    if re.match(r"^F\d+", ref_u) or (value and _FUSE_VALUE.search(value)):
        return True
    return False


def is_ic_like(ref: str | None, value: str | None) -> bool:
    ref_u = (ref or "").upper()
    if re.match(r"^U\d+", ref_u) or re.match(r"^IC\d+", ref_u):
        return True
    return bool(value and _REGULATOR_VALUE.search(value))


def is_regulator_like(ref: str | None, value: str | None) -> bool:
    return bool(value and _REGULATOR_VALUE.search(value)) or (
        (ref or "").upper().startswith("U") and bool(value and re.search(r"(?i)(reg|ldo|buck|boost|pmic)", value))
    )


@dataclass
class PadInfo:
    number: str | None
    net_id: int | None
    net_name: str | None
    at: list[float] | None = None


@dataclass
class FootprintRich:
    reference: str | None
    value: str | None
    at: list[float] | None
    pads: list[PadInfo] = field(default_factory=list)
    net_ids: set[int] = field(default_factory=set)
    net_names: set[str] = field(default_factory=set)


@dataclass
class ZoneInfo:
    net_id: int | None
    net_name: str | None
    layers: list[str]


@dataclass
class AnalysisContext:
    path: Path
    text: str
    summary: dict[str, Any]
    nets: list[dict[str, Any]]
    footprints: list[FootprintRich]
    zones: list[ZoneInfo]
    segments_by_net: dict[int, int]
    vias_by_net: dict[int, int]
    pads_parsed: int
    approximate: bool = True

    def net_by_id(self) -> dict[int, str]:
        return {int(n["id"]): str(n.get("name") or "") for n in self.nets if str(n.get("id", "")).isdigit()}


def _parse_top_level_nets(text: str) -> list[dict[str, Any]]:
    """Parse only top-level (net id "name") declarations, not pad-local nets."""
    nets: list[dict[str, Any]] = []
    seen: set[int] = set()
    for form in _top_level_forms(text, "net"):
        match = re.match(r'\(net\s+(\d+)\s+"([^"]*)"\s*\)', form.strip())
        if not match:
            # multi-line form
            match = re.search(r'\(net\s+(\d+)\s+"([^"]*)"', form)
        if not match:
            continue
        net_id = int(match.group(1))
        if net_id in seen:
            continue
        seen.add(net_id)
        nets.append({"id": net_id, "name": match.group(2)})
    return nets


def _parse_pad_net(form: str) -> PadInfo:
    number_match = re.search(r'\(pad\s+"([^"]*)"', form)
    net_match = re.search(r'\(net\s+(\d+)(?:\s+"([^"]*)")?\)', form)
    at_match = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", form)
    net_id = int(net_match.group(1)) if net_match else None
    net_name = net_match.group(2) if net_match and net_match.lastindex and net_match.lastindex >= 2 else None
    at = [float(at_match.group(1)), float(at_match.group(2))] if at_match else None
    return PadInfo(
        number=number_match.group(1) if number_match else None,
        net_id=net_id,
        net_name=net_name,
        at=at,
    )


def _nested_forms(text: str, keyword: str) -> list[str]:
    """Return nested S-expression forms for a keyword (pads inside footprints)."""
    matches = list(re.finditer(rf"\({re.escape(keyword)}(?:\s|\")", text))
    forms: list[str] = []
    for match in matches:
        depth, quoted, escaped = 0, False, False
        for index in range(match.start(), len(text)):
            char = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    forms.append(text[match.start() : index + 1])
                    break
    return forms


def _parse_footprints_rich(text: str) -> tuple[list[FootprintRich], int]:
    footprints: list[FootprintRich] = []
    pads_parsed = 0
    for form in _top_level_forms(text, "footprint"):
        ref = re.search(r'\(property "Reference" "([^"]*)"', form)
        value = re.search(r'\(property "Value" "([^"]*)"', form)
        at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", form)
        pads: list[PadInfo] = []
        for pad_form in _nested_forms(form, "pad"):
            pad = _parse_pad_net(pad_form)
            pads.append(pad)
            pads_parsed += 1
        net_ids = {p.net_id for p in pads if p.net_id is not None and p.net_id != 0}
        net_names = {p.net_name for p in pads if p.net_name}
        footprints.append(
            FootprintRich(
                reference=ref.group(1) if ref else None,
                value=value.group(1) if value else None,
                at=[float(v) for v in at.groups(default="0")[:2]] if at else None,
                pads=pads,
                net_ids=net_ids,
                net_names={n for n in net_names if n},
            )
        )
    return footprints, pads_parsed


def _parse_zones(text: str) -> list[ZoneInfo]:
    zones: list[ZoneInfo] = []
    for form in _top_level_forms(text, "zone"):
        net_match = re.search(r"\(net\s+(\d+)\)", form)
        name_match = re.search(r'\(net_name\s+"([^"]*)"\)', form)
        layers = re.findall(r'\(layer\s+"([^"]+)"\)', form)
        if not layers:
            layers = re.findall(r'\(layers\s+"([^"]+)"\)', form)
        zones.append(
            ZoneInfo(
                net_id=int(net_match.group(1)) if net_match else None,
                net_name=name_match.group(1) if name_match else None,
                layers=layers,
            )
        )
    return zones


def _count_geometry_by_net(text: str, keyword: str) -> dict[int, int]:
    counts: dict[int, int] = {}
    for form in _top_level_forms(text, keyword):
        net_match = re.search(r"\(net\s+(\d+)\)", form)
        if net_match:
            net_id = int(net_match.group(1))
            counts[net_id] = counts.get(net_id, 0) + 1
    return counts


def build_analysis_context(board: str | Path) -> AnalysisContext:
    path = resolve_path(board, ".kicad_pcb")
    if not path.is_file():
        raise KiClawError(f"Board not found: {path}")
    text = path.read_text(encoding="utf-8")
    summary = board_summary(path)
    nets = _parse_top_level_nets(text)
    if not nets:
        # Fallback: board_summary nets (may include pad noise) de-duplicated by id
        dedup: dict[int, str] = {}
        for item in summary.get("nets", []):
            try:
                dedup[int(item["id"])] = str(item.get("name") or "")
            except (KeyError, TypeError, ValueError):
                continue
        nets = [{"id": k, "name": v} for k, v in sorted(dedup.items())]
    footprints, pads_parsed = _parse_footprints_rich(text)
    return AnalysisContext(
        path=path,
        text=text,
        summary=summary,
        nets=nets,
        footprints=footprints,
        zones=_parse_zones(text),
        segments_by_net=_count_geometry_by_net(text, "segment"),
        vias_by_net=_count_geometry_by_net(text, "via"),
        pads_parsed=pads_parsed,
    )


def _attachments(ctx: AnalysisContext) -> dict[int, list[FootprintRich]]:
    index: dict[int, list[FootprintRich]] = {}
    for fp in ctx.footprints:
        for net_id in fp.net_ids:
            index.setdefault(net_id, []).append(fp)
    return index


def _distance(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) < 2 or len(b) < 2:
        return None
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _pack_result(
    name: str,
    findings: list[dict[str, Any]],
    result: dict[str, Any],
    confidence: str = "medium",
) -> dict[str, Any]:
    counts = _finding_counts(findings)
    blocking = sum(counts.get(severity, 0) for severity in ("error", "critical", "unknown"))
    return {
        "pack": name,
        "ok": blocking == 0,
        "findings": findings,
        "finding_counts": counts,
        "result": result,
        "confidence": confidence,
        "evidence": ANALYSIS_EVIDENCE,
        "disclaimer": ANALYSIS_DISCLAIMER,
        "approximate": True,
    }


def analyze_power_tree(ctx: AnalysisContext) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    attachments = _attachments(ctx)
    power_nets = []
    for net in ctx.nets:
        name = str(net.get("name") or "")
        tags = classify_net_name(name)
        if "power" not in tags or "ground" in tags:
            continue
        net_id = int(net["id"])
        fps = attachments.get(net_id, [])
        refs = sorted({fp.reference for fp in fps if fp.reference})
        entry = {
            "id": net_id,
            "name": name,
            "tags": sorted(tags),
            "pad_footprints": len(refs),
            "footprint_refs": refs,
            "segment_count": ctx.segments_by_net.get(net_id, 0),
            "via_count": ctx.vias_by_net.get(net_id, 0),
            "zone_count": sum(1 for z in ctx.zones if z.net_id == net_id),
            "regulators_nearby": sorted(
                {fp.reference for fp in fps if fp.reference and is_regulator_like(fp.reference, fp.value)}
            ),
        }
        power_nets.append(entry)
        if not refs and entry["zone_count"] == 0 and entry["segment_count"] == 0:
            findings.append(
                _finding(
                    "power_tree",
                    "warning",
                    f"Power-like net {name!r} has no pad attachments, copper segments, or zones on the PCB.",
                    ANALYSIS_EVIDENCE,
                    "medium",
                    entry,
                )
            )
        elif not refs:
            findings.append(
                _finding(
                    "power_tree",
                    "warning",
                    f"Power-like net {name!r} has copper but no footprint pads attached.",
                    ANALYSIS_EVIDENCE,
                    "medium",
                    entry,
                )
            )

    # Name-hierarchy clusters (not electrical topology)
    clusters: dict[str, list[str]] = {}
    for item in power_nets:
        base = re.sub(r"(_[A-Z0-9]+)$", "", item["name"].upper().lstrip("/+"))
        base = re.sub(r"\d+$", "", base) or item["name"]
        clusters.setdefault(base, []).append(item["name"])

    if not power_nets:
        findings.append(
            _finding(
                "power_tree",
                "warning",
                "No nets matched power-name heuristics (VCC/VDD/+3V3/…).",
                ANALYSIS_EVIDENCE,
                "medium",
                {"nets_checked": len(ctx.nets)},
            )
        )

    return _pack_result(
        "power_tree",
        findings,
        {
            "power_nets": power_nets,
            "name_clusters": {k: v for k, v in clusters.items() if len(v) > 1},
            "note": "Clusters are name-prefix groups only; regulator topology is not inferred.",
        },
        confidence="medium",
    )


def analyze_decoupling(ctx: AnalysisContext, max_distance_mm: float = 5.0) -> dict[str, Any]:
    max_distance_mm = _finite_positive("max_distance_mm", max_distance_mm)
    findings: list[dict[str, Any]] = []
    caps = [fp for fp in ctx.footprints if is_capacitor(fp.reference, fp.value)]
    ics = [fp for fp in ctx.footprints if is_ic_like(fp.reference, fp.value)]
    power_ids = {
        int(n["id"])
        for n in ctx.nets
        if "power" in classify_net_name(str(n.get("name") or "")) and "ground" not in classify_net_name(str(n.get("name") or ""))
    }
    attachments = _attachments(ctx)
    per_rail: list[dict[str, Any]] = []
    method = "pad_net+proximity" if ctx.pads_parsed else "presence_only"

    if not ctx.pads_parsed:
        if power_ids and not caps:
            findings.append(
                _finding(
                    "decoupling",
                    "warning",
                    "Power-like nets exist but no capacitor footprints were identified; pad nets were not available for a proximity audit.",
                    ANALYSIS_EVIDENCE,
                    "low",
                    {"method": method, "power_net_count": len(power_ids)},
                )
            )
        return _pack_result(
            "decoupling",
            findings,
            {"method": method, "capacitors": len(caps), "ics": len(ics), "rails": []},
            confidence="low",
        )

    for net in ctx.nets:
        net_id = int(net["id"])
        if net_id not in power_ids:
            continue
        name = str(net.get("name") or "")
        on_rail = attachments.get(net_id, [])
        rail_caps = [fp for fp in on_rail if is_capacitor(fp.reference, fp.value)]
        rail_ics = [fp for fp in on_rail if is_ic_like(fp.reference, fp.value)]
        far_ics = []
        for ic in rail_ics:
            nearby = [
                cap.reference
                for cap in rail_caps
                if _distance(ic.at, cap.at) is not None and _distance(ic.at, cap.at) <= max_distance_mm  # type: ignore[operator]
            ]
            if not nearby:
                # also allow any cap within radius even if not pad-parsed on same net (rare)
                nearby = [
                    cap.reference
                    for cap in caps
                    if cap.reference
                    and net_id in cap.net_ids
                    and _distance(ic.at, cap.at) is not None
                    and _distance(ic.at, cap.at) <= max_distance_mm  # type: ignore[operator]
                ]
            if not nearby and ic.reference:
                far_ics.append(ic.reference)
                findings.append(
                    _finding(
                        "decoupling",
                        "warning",
                        f"IC-like footprint {ic.reference} is on power net {name!r} without a capacitor footprint within {max_distance_mm} mm (origin-to-origin).",
                        ANALYSIS_EVIDENCE,
                        "medium",
                        {
                            "power_net": name,
                            "ic": ic.reference,
                            "max_distance_mm": max_distance_mm,
                            "caps_on_rail": [c.reference for c in rail_caps if c.reference],
                            "method": method,
                        },
                    )
                )
        if rail_ics and not rail_caps:
            findings.append(
                _finding(
                    "decoupling",
                    "warning",
                    f"Power net {name!r} has IC-like footprints but no capacitor footprints sharing that net.",
                    ANALYSIS_EVIDENCE,
                    "medium",
                    {"power_net": name, "ics": [i.reference for i in rail_ics if i.reference]},
                )
            )
        per_rail.append(
            {
                "name": name,
                "id": net_id,
                "cap_count": len(rail_caps),
                "ic_count": len(rail_ics),
                "caps": [c.reference for c in rail_caps if c.reference],
                "ics": [i.reference for i in rail_ics if i.reference],
                "ics_without_nearby_cap": far_ics,
            }
        )

    if power_ids and not caps:
        findings.append(
            _finding(
                "decoupling",
                "warning",
                "Power-like nets exist but no capacitor-like footprints were found on the board.",
                ANALYSIS_EVIDENCE,
                "medium",
                {"power_net_count": len(power_ids)},
            )
        )

    return _pack_result(
        "decoupling",
        findings,
        {
            "method": method,
            "max_distance_mm": max_distance_mm,
            "capacitors": [{"ref": c.reference, "value": c.value} for c in caps if c.reference],
            "rails": per_rail,
            "note": "Distances use footprint origins, not pin centers; bulk vs HF caps are not distinguished.",
        },
        confidence="medium" if ctx.pads_parsed else "low",
    )


def analyze_protection(ctx: AnalysisContext, max_distance_mm: float = 15.0) -> dict[str, Any]:
    max_distance_mm = _finite_positive("max_distance_mm", max_distance_mm)
    findings: list[dict[str, Any]] = []
    connectors = [fp for fp in ctx.footprints if is_connector(fp.reference, fp.value)]
    protection = [fp for fp in ctx.footprints if is_protection(fp.reference, fp.value)]
    method = "pad_net+proximity" if ctx.pads_parsed else "presence_only"
    audits: list[dict[str, Any]] = []

    if not connectors:
        return _pack_result(
            "protection",
            findings,
            {
                "method": method,
                "connectors": [],
                "protection": [{"ref": p.reference, "value": p.value} for p in protection],
                "audits": [],
            },
            confidence="medium",
        )

    for conn in connectors:
        shared = []
        nearby = []
        for prot in protection:
            if conn.net_ids & prot.net_ids:
                shared.append(prot.reference)
            dist = _distance(conn.at, prot.at)
            if dist is not None and dist <= max_distance_mm:
                nearby.append({"ref": prot.reference, "distance_mm": round(dist, 3)})
        covered = bool(shared or nearby)
        entry = {
            "connector": conn.reference,
            "value": conn.value,
            "net_names": sorted(conn.net_names),
            "shared_protection": [r for r in shared if r],
            "nearby_protection": nearby,
            "covered": covered,
        }
        audits.append(entry)
        if not covered:
            findings.append(
                _finding(
                    "protection",
                    "warning",
                    f"Connector-like footprint {conn.reference} has no protection footprint on a shared net or within {max_distance_mm} mm.",
                    ANALYSIS_EVIDENCE,
                    "medium" if ctx.pads_parsed else "low",
                    {**entry, "method": method, "max_distance_mm": max_distance_mm},
                )
            )

    if connectors and not protection:
        findings.append(
            _finding(
                "protection",
                "warning",
                f"{len(connectors)} connector-like footprint(s) found with no TVS/ESD/fuse-like protection footprints on the board.",
                ANALYSIS_EVIDENCE,
                "low",
                {"connectors": [c.reference for c in connectors if c.reference]},
            )
        )

    return _pack_result(
        "protection",
        findings,
        {
            "method": method,
            "max_distance_mm": max_distance_mm,
            "connectors": [{"ref": c.reference, "value": c.value, "nets": sorted(c.net_names)} for c in connectors],
            "protection": [{"ref": p.reference, "value": p.value, "nets": sorted(p.net_names)} for p in protection],
            "audits": audits,
            "note": "Internal board-to-board headers may not need external ESD devices; treat as review prompts.",
        },
        confidence="medium" if ctx.pads_parsed else "low",
    )


def analyze_net_clusters(ctx: AnalysisContext) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    clusters: dict[str, list[str]] = {
        "power": [],
        "ground": [],
        "clock": [],
        "usb": [],
        "i2c": [],
        "spi": [],
        "uart": [],
        "can": [],
        "diff": [],
        "analog": [],
        "signal": [],
    }
    for net in ctx.nets:
        name = str(net.get("name") or "")
        if not name or int(net["id"]) == 0:
            continue
        tags = classify_net_name(name)
        for tag in tags:
            if tag in clusters:
                clusters[tag].append(name)

    # One-sided interface heuristics (low confidence)
    names_upper = {str(n.get("name") or "").upper() for n in ctx.nets}
    if any("SDA" in n for n in names_upper) and not any("SCL" in n for n in names_upper):
        findings.append(
            _finding(
                "net_class",
                "warning",
                "I2C-like SDA net name found without a complementary SCL-like net name.",
                ANALYSIS_EVIDENCE,
                "low",
                {"cluster": "i2c"},
            )
        )
    if any(re.search(r"(?i)USB.*D\+|DP|USB_DP", n) for n in names_upper) and not any(
        re.search(r"(?i)USB.*D-|DM|USB_DM", n) for n in names_upper
    ):
        findings.append(
            _finding(
                "net_class",
                "warning",
                "USB differential positive-like name found without a complementary negative/DM name.",
                ANALYSIS_EVIDENCE,
                "low",
                {"cluster": "usb"},
            )
        )

    non_empty = {k: sorted(set(v)) for k, v in clusters.items() if v}
    return _pack_result(
        "net_clusters",
        findings,
        {
            "clusters": non_empty,
            "counts": {k: len(v) for k, v in non_empty.items()},
            "note": "Buckets are regex/name conventions, not KiCad net classes or electrical domains.",
        },
        confidence="medium",
    )


def analyze_ground_strategy(ctx: AnalysisContext) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    attachments = _attachments(ctx)
    grounds = []
    for net in ctx.nets:
        name = str(net.get("name") or "")
        if "ground" not in classify_net_name(name):
            continue
        net_id = int(net["id"])
        refs = sorted({fp.reference for fp in attachments.get(net_id, []) if fp.reference})
        zone_count = sum(1 for z in ctx.zones if z.net_id == net_id)
        entry = {
            "id": net_id,
            "name": name,
            "pad_footprints": len(refs),
            "footprint_refs": refs,
            "zone_count": zone_count,
            "via_count": ctx.vias_by_net.get(net_id, 0),
            "segment_count": ctx.segments_by_net.get(net_id, 0),
        }
        grounds.append(entry)
        if refs and zone_count == 0:
            findings.append(
                _finding(
                    "ground",
                    "warning",
                    f"Ground net {name!r} has footprint attachments but no copper zone tied to that net id.",
                    ANALYSIS_EVIDENCE,
                    "high",
                    entry,
                )
            )

    if not grounds:
        findings.append(
            _finding(
                "ground",
                "warning",
                "No conventional ground net names were detected (GND/AGND/DGND/…).",
                ANALYSIS_EVIDENCE,
                "medium",
            )
        )
    elif len(grounds) > 1:
        findings.append(
            _finding(
                "ground",
                "warning",
                f"Multiple ground net names detected ({', '.join(g['name'] for g in grounds)}); isolation/stitching is not verified.",
                ANALYSIS_EVIDENCE,
                "medium",
                {"grounds": [g["name"] for g in grounds]},
            )
        )

    return _pack_result(
        "ground",
        findings,
        {
            "grounds": grounds,
            "note": "Zone presence is structural only; return-path quality is not simulated.",
        },
        confidence="high" if grounds else "medium",
    )


def analyze_connectivity_gaps(ctx: AnalysisContext, strict: bool = False) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if not ctx.footprints:
        return _pack_result(
            "connectivity",
            findings,
            {"skipped": True, "reason": "No footprints on board", "orphans": [], "unused_nets": []},
            confidence="high",
        )
    if ctx.pads_parsed == 0:
        findings.append(
            _finding(
                "connectivity",
                "warning",
                "Pad net fields were not detected on any footprint; connectivity gap audit was skipped.",
                ANALYSIS_EVIDENCE,
                "high",
                {"footprints": len(ctx.footprints), "pads_parsed": 0},
            )
        )
        return _pack_result(
            "connectivity",
            findings,
            {"skipped": True, "reason": "No pad nets parsed", "orphans": [], "unused_nets": [], "pads_parsed": 0},
            confidence="high",
        )

    pad_counts: dict[int, int] = {}
    refs_by_net: dict[int, set[str]] = {}
    for fp in ctx.footprints:
        for pad in fp.pads:
            if pad.net_id is None or pad.net_id == 0:
                continue
            pad_counts[pad.net_id] = pad_counts.get(pad.net_id, 0) + 1
            if fp.reference:
                refs_by_net.setdefault(pad.net_id, set()).add(fp.reference)

    net_by_id = ctx.net_by_id()
    orphans = []
    unused = []
    severity = "error" if strict else "warning"
    for net_id, count in sorted(pad_counts.items()):
        name = net_by_id.get(net_id, "")
        if name.startswith("unconnected-") or "unconnected" in name.lower():
            continue
        refs = sorted(refs_by_net.get(net_id, set()))
        if count == 1:
            entry = {"id": net_id, "name": name, "pad_count": count, "footprint_refs": refs}
            orphans.append(entry)
            findings.append(
                _finding(
                    "connectivity",
                    severity,
                    f"Net {name or net_id} has only one pad attachment on the PCB (possible antenna or incomplete connection).",
                    ANALYSIS_EVIDENCE,
                    "high",
                    entry,
                )
            )

    for net in ctx.nets:
        net_id = int(net["id"])
        name = str(net.get("name") or "")
        if net_id == 0 or not name or name.startswith("unconnected-"):
            continue
        if pad_counts.get(net_id, 0) == 0:
            zone_count = sum(1 for z in ctx.zones if z.net_id == net_id)
            seg = ctx.segments_by_net.get(net_id, 0)
            if zone_count == 0 and seg == 0:
                entry = {"id": net_id, "name": name, "pad_count": 0, "zone_count": zone_count, "segment_count": seg}
                unused.append(entry)
                findings.append(
                    _finding(
                        "connectivity",
                        "warning",
                        f"Named net {name!r} has no pad attachments, segments, or zones on the PCB.",
                        ANALYSIS_EVIDENCE,
                        "medium",
                        entry,
                    )
                )

    return _pack_result(
        "connectivity",
        findings,
        {
            "skipped": False,
            "pads_parsed": ctx.pads_parsed,
            "nets_with_pads": len(pad_counts),
            "orphans": orphans,
            "unused_nets": unused,
            "strict": strict,
            "note": "PCB pad graph only; schematic intent and intentional testpoints are not distinguished.",
        },
        confidence="high",
    )


_PACK_RUNNERS = {
    "power_tree": lambda ctx, **kw: analyze_power_tree(ctx),
    "decoupling": lambda ctx, **kw: analyze_decoupling(ctx, kw.get("max_decoupling_distance_mm", 5.0)),
    "protection": lambda ctx, **kw: analyze_protection(ctx, kw.get("max_protection_distance_mm", 15.0)),
    "net_clusters": lambda ctx, **kw: analyze_net_clusters(ctx),
    "ground": lambda ctx, **kw: analyze_ground_strategy(ctx),
    "connectivity": lambda ctx, **kw: analyze_connectivity_gaps(ctx, kw.get("strict_connectivity", False)),
}


def run_analysis(
    board: str | Path,
    packs: Sequence[str] | None = None,
    *,
    max_decoupling_distance_mm: float = 5.0,
    max_protection_distance_mm: float = 15.0,
    strict_connectivity: bool = False,
) -> dict[str, Any]:
    """Run selectable deterministic deep-analysis packs on a board file."""
    selected = tuple(packs) if packs else DEFAULT_PACKS
    unknown = [name for name in selected if name not in _PACK_RUNNERS]
    if unknown:
        raise KiClawError(f"Unknown analysis pack(s): {', '.join(unknown)}. Valid: {', '.join(DEFAULT_PACKS)}")
    ctx = build_analysis_context(board)
    profile = {
        "packs": list(selected),
        "max_decoupling_distance_mm": max_decoupling_distance_mm,
        "max_protection_distance_mm": max_protection_distance_mm,
        "strict_connectivity": strict_connectivity,
    }
    pack_kwargs = {
        "max_decoupling_distance_mm": max_decoupling_distance_mm,
        "max_protection_distance_mm": max_protection_distance_mm,
        "strict_connectivity": strict_connectivity,
    }
    pack_results: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    for name in selected:
        result = _PACK_RUNNERS[name](ctx, **pack_kwargs)
        pack_results[name] = result
        findings.extend(result["findings"])

    counts = _finding_counts(findings)
    blocking = sum(counts.get(severity, 0) for severity in ("error", "critical", "unknown"))
    return {
        "ok": blocking == 0,
        "board": ctx.summary,
        "approximate": True,
        "pads_parsed": ctx.pads_parsed,
        "profile": profile,
        "packs": pack_results,
        "findings": findings,
        "finding_counts": counts,
        "confidence": "medium",
        "evidence": ANALYSIS_EVIDENCE,
        "disclaimer": ANALYSIS_DISCLAIMER,
    }


def run_deep_analysis(board: str | Path, **kwargs: Any) -> dict[str, Any]:
    """Alias for :func:`run_analysis`."""
    return run_analysis(board, **kwargs)
