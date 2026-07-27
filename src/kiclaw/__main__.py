from __future__ import annotations

import argparse
import json
import logging
import sys

from .core import add_component, add_custom_component, add_wire, capability_report, compatibility_report, datasheet_evidence, review_project, run_analysis, run_dfm, run_emc, run_si, run_spice, run_thermal, schematic_roundtrip_check, spice_capability


def main() -> None:
    parser = argparse.ArgumentParser(prog="kiclaw")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="print the detected KiCad backend matrix")
    review = commands.add_parser("review", help="run a deterministic project review and print JSON")
    review.add_argument("path", help="project directory, board, or schematic")
    review.add_argument("--output", help="also write the JSON report to this file")
    review.add_argument("--fail-on-warning", action="store_true", help="return failure when warnings are present")
    dfm = commands.add_parser("dfm", help="run deterministic DFM checks and print JSON")
    dfm.add_argument("path", help=".kicad_pcb file")
    dfm.add_argument("--minimum-trace-width", type=float, default=0.15)
    dfm.add_argument("--require-fiducials", action="store_true")
    dfm.add_argument("--require-testpoints", action="store_true")
    emc = commands.add_parser("emc", help="run conservative EMC pre-compliance heuristics")
    emc.add_argument("path", help=".kicad_pcb file")
    emc.add_argument("--profile", default="conservative", choices=["conservative"])
    si = commands.add_parser("si", help="run conservative signal-integrity indicators")
    si.add_argument("path", help=".kicad_pcb file")
    si.add_argument("--max-segment-length", type=float, default=10.0)
    thermal = commands.add_parser("thermal", help="run conservative thermal indicators")
    thermal.add_argument("path", help=".kicad_pcb file")
    thermal.add_argument("--profile", default="conservative", choices=["conservative"])
    analyze = commands.add_parser("analyze", help="run deterministic deep analysis packs (power, decoupling, protection, …)")
    analyze.add_argument("path", help=".kicad_pcb file")
    analyze.add_argument("--packs", help="comma-separated packs: power_tree,decoupling,protection,net_clusters,ground,connectivity")
    analyze.add_argument("--max-decoupling-distance", type=float, default=5.0)
    analyze.add_argument("--max-protection-distance", type=float, default=15.0)
    analyze.add_argument("--strict-connectivity", action="store_true", help="promote single-pad nets to error severity")
    analyze.add_argument("--output", help="also write the JSON report to this file")
    analyze.add_argument("--fail-on-warning", action="store_true")
    evidence = commands.add_parser("evidence", help="hash a datasheet artifact and score explicit text claims")
    evidence.add_argument("source", help="local path or http(s) URL")
    evidence.add_argument("--claim", action="append", dest="claims", default=[])
    evidence.add_argument("--max-bytes", type=int, default=5_000_000)
    compatibility = commands.add_parser("compatibility", help="report KiCad/backend compatibility for this host")
    compatibility.add_argument("path", nargs="?", help="optional project directory, board, or schematic to exercise")
    spice = commands.add_parser("spice", help="run an ngspice netlist or report SPICE capability")
    spice.add_argument("path", nargs="?", help="SPICE netlist; omit to report capability")
    spice.add_argument("--timeout", type=int, default=120)
    schematic_check = commands.add_parser("schematic-check", help="verify schematic structure and byte-preserving round-trip")
    schematic_check.add_argument("path", help=".kicad_sch file")
    schematic_wire = commands.add_parser("schematic-add-wire", help="add one guarded schematic wire")
    schematic_wire.add_argument("path", help=".kicad_sch file")
    schematic_wire.add_argument("start_x", type=float)
    schematic_wire.add_argument("start_y", type=float)
    schematic_wire.add_argument("end_x", type=float)
    schematic_wire.add_argument("end_y", type=float)
    schematic_wire.add_argument("--expected-sha256")
    schematic_component = commands.add_parser("schematic-add-component", help="clone an existing symbol instance with guards")
    schematic_component.add_argument("path", help=".kicad_sch file")
    schematic_component.add_argument("lib_id")
    schematic_component.add_argument("reference")
    schematic_component.add_argument("x", type=float)
    schematic_component.add_argument("y", type=float)
    schematic_component.add_argument("--value")
    schematic_component.add_argument("--rotation", type=float, default=0.0)
    schematic_component.add_argument("--expected-sha256")
    custom_component = commands.add_parser("schematic-add-custom-component", help="generate a project-local symbol library and place a cloned symbol")
    custom_component.add_argument("path", help=".kicad_sch file")
    custom_component.add_argument("source_lib_id")
    custom_component.add_argument("new_lib_id")
    custom_component.add_argument("reference")
    custom_component.add_argument("x", type=float)
    custom_component.add_argument("y", type=float)
    custom_component.add_argument("--value")
    custom_component.add_argument("--rotation", type=float, default=0.0)
    custom_component.add_argument("--expected-sha256")
    serve = commands.add_parser("serve", help="run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=3334)
    serve.add_argument("--verbose", action="store_true", help="show detailed MCP tool progress on stderr")
    args = parser.parse_args()
    if args.command == "doctor":
        print(json.dumps(capability_report(), indent=2))
        return
    if args.command == "review":
        result = review_project(args.path)
        rendered = json.dumps(result, indent=2)
        print(rendered)
        if args.output:
            from pathlib import Path
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        if not result["ok"] or (args.fail_on_warning and result.get("finding_counts", {}).get("warning", 0)):
            raise SystemExit(1)
        return
    if args.command == "dfm":
        result = run_dfm(args.path, args.minimum_trace_width, args.require_fiducials, args.require_testpoints)
        print(json.dumps(result, indent=2))
        if not result["ok"]:
            raise SystemExit(1)
        return
    if args.command == "emc":
        print(json.dumps(run_emc(args.path, args.profile), indent=2))
        return
    if args.command == "si":
        print(json.dumps(run_si(args.path, args.max_segment_length), indent=2))
        return
    if args.command == "thermal":
        print(json.dumps(run_thermal(args.path, args.profile), indent=2))
        return
    if args.command == "analyze":
        packs = [item.strip() for item in args.packs.split(",") if item.strip()] if args.packs else None
        result = run_analysis(
            args.path,
            packs=packs,
            max_decoupling_distance_mm=args.max_decoupling_distance,
            max_protection_distance_mm=args.max_protection_distance,
            strict_connectivity=args.strict_connectivity,
        )
        rendered = json.dumps(result, indent=2)
        print(rendered)
        if args.output:
            from pathlib import Path
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        if not result["ok"] or (args.fail_on_warning and result.get("finding_counts", {}).get("warning", 0)):
            raise SystemExit(1)
        return
    if args.command == "evidence":
        print(json.dumps(datasheet_evidence(args.source, args.claims, args.max_bytes), indent=2))
        return
    if args.command == "compatibility":
        print(json.dumps(compatibility_report(args.path), indent=2))
        return
    if args.command == "spice":
        result = spice_capability() if not args.path else run_spice(args.path, args.timeout)
        print(json.dumps(result, indent=2))
        return
    if args.command == "schematic-check":
        result = schematic_roundtrip_check(args.path)
        print(json.dumps(result, indent=2))
        if not result["ok"]:
            raise SystemExit(1)
        return
    if args.command == "schematic-add-wire":
        result = add_wire(args.path, args.start_x, args.start_y, args.end_x, args.end_y, args.expected_sha256)
        print(json.dumps(result, indent=2))
        return
    if args.command == "schematic-add-component":
        result = add_component(args.path, args.lib_id, args.reference, args.x, args.y, args.value, args.rotation, args.expected_sha256)
        print(json.dumps(result, indent=2))
        return
    if args.command == "schematic-add-custom-component":
        result = add_custom_component(args.path, args.source_lib_id, args.new_lib_id, args.reference, args.x, args.y, args.value, args.rotation, args.expected_sha256)
        print(json.dumps(result, indent=2))
        return
    # Import the MCP/Pydantic stack only for the server command.  Inspection,
    # review, and help/doctor commands should remain fast and independent of
    # MCP's optional web/session dependencies.
    from .server import mcp

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[KiClaw] %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("kiclaw").info("MCP server ready | transport=%s", args.transport)
    mcp.settings.host, mcp.settings.port = args.host, args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
