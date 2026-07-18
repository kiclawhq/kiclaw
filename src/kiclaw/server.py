"""The MCP surface. Domain work stays in :mod:`kiclaw.core` for testability."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .core import (add_component, add_custom_component, add_track, add_wire, backend_session_info, board_summary, capability_report, compatibility_report, datasheet_evidence, ipc_board_status, ipc_move_footprint, ipc_session_info, move_footprint, pcb_backend_policy, project_info, review_board, review_project, run_check, run_dfm, run_emc, run_export, run_si, run_spice, run_thermal, schematic_roundtrip_check, schematic_summary, spice_capability,
                   snapshot_create, snapshot_list, snapshot_restore)

mcp = FastMCP("KiClaw", instructions="Use capability_report first. File-derived board statistics are approximate; ERC/DRC and exports come from KiCad.")


@mcp.tool(name="capability_report")
def capability_report_tool() -> dict[str, Any]:
    """Report which KiCad backends are genuinely available on this machine."""
    return capability_report()


@mcp.tool(name="open_project")
def open_project(path: str) -> dict[str, Any]:
    """Discover KiCad boards and schematics in a project directory."""
    return project_info(path)


@mcp.tool(name="project_info")
def project_info_tool(path: str) -> dict[str, Any]:
    """Return project file locations without modifying the project."""
    return project_info(path)


@mcp.tool(name="datasheet_evidence")
def datasheet_evidence_tool(source: str, claims: list[str] | None = None, max_bytes: int = 5_000_000) -> dict[str, Any]:
    """Hash a local/HTTP datasheet artifact and score only explicitly requested text claims."""
    return datasheet_evidence(source, claims, max_bytes)


@mcp.tool(name="compatibility_report")
def compatibility_report_tool(project: str | None = None) -> dict[str, Any]:
    """Report detected KiCad version/backends and optionally run native checks on a project."""
    return compatibility_report(project)


@mcp.tool(name="spice_capability")
def spice_capability_tool() -> dict[str, Any]:
    """Report whether an ngspice batch backend is installed."""
    return spice_capability()


@mcp.tool(name="run_spice")
def run_spice_tool(netlist: str, timeout: int = 120) -> dict[str, Any]:
    """Run a supplied SPICE netlist through ngspice batch mode when available."""
    return run_spice(netlist, timeout)


@mcp.tool(name="get_board_status")
def get_board_status(board: str) -> dict[str, Any]:
    """Return an approximate structural board summary plus real DRC when available."""
    return {"board": board_summary(board), "drc": run_check("drc", board)}


@mcp.tool(name="pcb_statistics")
def pcb_statistics(board: str) -> dict[str, Any]:
    """Return approximate counts of footprints, nets, tracks, vias, and zones."""
    return board_summary(board)["statistics"] | {"approximate": True}


@mcp.tool(name="list_footprints")
def list_footprints(board: str) -> dict[str, Any]:
    """List approximate footprint reference, value, and location data."""
    summary = board_summary(board)
    return {"approximate": True, "footprints": summary["footprints"]}


@mcp.tool(name="list_nets")
def list_nets(board: str) -> dict[str, Any]:
    """List nets parsed from a board file."""
    summary = board_summary(board)
    return {"approximate": True, "nets": summary["nets"]}


@mcp.tool(name="schematic_summary")
def schematic_summary_tool(schematic: str) -> dict[str, Any]:
    """Return structural schematic metadata without rewriting the source."""
    return schematic_summary(schematic)


@mcp.tool(name="schematic_roundtrip_check")
def schematic_roundtrip_check_tool(schematic: str) -> dict[str, Any]:
    """Verify that the schematic parser boundary preserves the original bytes."""
    return schematic_roundtrip_check(schematic)


@mcp.tool(name="add_wire")
def add_wire_tool(schematic: str, start_x: float, start_y: float, end_x: float, end_y: float, expected_sha256: str | None = None) -> dict[str, Any]:
    """Add one schematic wire with snapshot, hash guard, round-trip verification, and ERC."""
    return add_wire(schematic, start_x, start_y, end_x, end_y, expected_sha256)


@mcp.tool(name="add_component")
def add_component_tool(schematic: str, lib_id: str, reference: str, x: float, y: float, value: str | None = None, rotation: float = 0.0, expected_sha256: str | None = None) -> dict[str, Any]:
    """Clone an existing schematic symbol instance with guarded placement and ERC verification."""
    return add_component(schematic, lib_id, reference, x, y, value, rotation, expected_sha256)


@mcp.tool(name="add_custom_component")
def add_custom_component_tool(schematic: str, source_lib_id: str, new_lib_id: str, reference: str, x: float, y: float, value: str | None = None, rotation: float = 0.0, expected_sha256: str | None = None) -> dict[str, Any]:
    """Clone a known-good symbol into a project-local library, register it, and verify KiCad can load it."""
    return add_custom_component(schematic, source_lib_id, new_lib_id, reference, x, y, value, rotation, expected_sha256)


@mcp.tool(name="run_drc")
def run_drc(board: str) -> dict[str, Any]:
    """Run KiCad's native DRC and return its JSON report."""
    return run_check("drc", board)


@mcp.tool(name="run_erc")
def run_erc(schematic: str) -> dict[str, Any]:
    """Run KiCad's native ERC and return its JSON report."""
    return run_check("erc", schematic)


@mcp.tool(name="export_gerbers")
def export_gerbers(board: str, output_directory: str) -> dict[str, Any]:
    """Generate fabrication Gerbers through KiCad's CLI."""
    return run_export("gerbers", board, output_directory)


@mcp.tool(name="export_drill")
def export_drill(board: str, output_directory: str) -> dict[str, Any]:
    """Generate drill files through KiCad's CLI."""
    return run_export("drill", board, output_directory)


@mcp.tool(name="export_svg")
def export_svg(board: str, output_file: str) -> dict[str, Any]:
    """Render selected board layers to one SVG using KiCad's CLI."""
    return run_export("svg", board, output_file)


@mcp.tool(name="export_ipc2581")
def export_ipc2581(board: str, output_file: str) -> dict[str, Any]:
    """Generate a fabrication and assembly IPC-2581 package through KiCad's CLI."""
    return run_export("ipc2581", board, output_file)


@mcp.tool(name="snapshot_create")
def snapshot_create_tool(board: str, label: str = "manual") -> dict[str, Any]:
    """Create a recoverable board snapshot before a risky action."""
    return snapshot_create(board, label)


@mcp.tool(name="snapshot_list")
def snapshot_list_tool(board: str) -> list[dict[str, Any]]:
    """List recoverable snapshots for this board."""
    return snapshot_list(board)


@mcp.tool(name="snapshot_restore")
def snapshot_restore_tool(board: str, snapshot_id: str, expected_sha256: str | None = None, force: bool = False) -> dict[str, Any]:
    """Restore a snapshot, first creating a safety snapshot of the current board."""
    return snapshot_restore(board, snapshot_id, expected_sha256, force)


@mcp.tool(name="add_track")
def add_track_tool(board: str, net_name: str, start_x: float, start_y: float, end_x: float, end_y: float, width: float = 0.25, layer: str = "F.Cu", expected_sha256: str | None = None) -> dict[str, Any]:
    """Insert one straight F.Cu/B.Cu segment, then snapshot, diff, and DRC-check it."""
    return add_track(board, net_name, start_x, start_y, end_x, end_y, width, layer, expected_sha256)


@mcp.tool(name="move_footprint")
def move_footprint_tool(board: str, reference: str, x: float, y: float, rotation: float | None = None, expected_sha256: str | None = None, backend: str = "auto") -> dict[str, Any]:
    """Move a footprint using live IPC when available, otherwise guarded file/CLI fallback."""
    return move_footprint(board, reference, x, y, rotation, expected_sha256, backend)


@mcp.tool(name="pcb_backend_policy")
def pcb_backend_policy_tool(board: str | None = None, requested: str = "auto") -> dict[str, Any]:
    """Report or select the PCB backend without changing a document."""
    return pcb_backend_policy(board, requested)


@mcp.tool(name="verify_last_action")
def verify_last_action(board: str) -> dict[str, Any]:
    """Re-run native DRC and return the present board state after an action."""
    return {"board": board_summary(board), "drc": run_check("drc", board), "snapshots": snapshot_list(board)[:5]}


@mcp.tool(name="review_board")
def review_board_tool(board: str) -> dict[str, Any]:
    """Run the evidence-labelled first-pass manufacturing review."""
    return review_board(board)


@mcp.tool(name="run_dfm")
def run_dfm_tool(board: str, minimum_trace_width: float = 0.15, require_fiducials: bool = False, require_testpoints: bool = False) -> dict[str, Any]:
    """Run deterministic profile-controlled DFM checks without modifying the board."""
    return run_dfm(board, minimum_trace_width, require_fiducials, require_testpoints)


@mcp.tool(name="run_emc")
def run_emc_tool(board: str, profile: str = "conservative") -> dict[str, Any]:
    """Run conservative EMC pre-compliance heuristics without modifying the board."""
    return run_emc(board, profile)


@mcp.tool(name="run_si")
def run_si_tool(board: str, max_segment_length: float = 10.0) -> dict[str, Any]:
    """Run conservative SI/PI indicators without modifying the board."""
    return run_si(board, max_segment_length)


@mcp.tool(name="run_thermal")
def run_thermal_tool(board: str, profile: str = "conservative") -> dict[str, Any]:
    """Run conservative thermal-management indicators without modifying the board."""
    return run_thermal(board, profile)


@mcp.tool(name="review_project")
def review_project_tool(project: str) -> dict[str, Any]:
    """Review every board and schematic in a project with evidence-labelled findings."""
    return review_project(project)


@mcp.tool(name="ipc_session_info")
def ipc_session_info_tool() -> dict[str, Any]:
    """Read the live KiCad IPC session without changing any document."""
    return ipc_session_info()


@mcp.tool(name="backend_session_info")
def backend_session_info_tool(board: str) -> dict[str, Any]:
    """Report the backend pinned to a board's transaction session."""
    return backend_session_info(board)


@mcp.tool(name="ipc_board_status")
def ipc_board_status_tool() -> dict[str, Any]:
    """Read the active PCB through KiCad IPC, when a live session is available."""
    return ipc_board_status()


@mcp.tool(name="ipc_move_footprint")
def ipc_move_footprint_tool(board: str, reference: str, x: float, y: float, rotation: float | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    """Move one footprint in the active KiCad document through IPC; saving remains explicit."""
    return ipc_move_footprint(board, reference, x, y, rotation, expected_sha256)


_TOOL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "inspect": ("capability_report", "compatibility_report", "open_project", "project_info", "datasheet_evidence", "get_board_status", "pcb_statistics", "list_footprints", "list_nets", "schematic_summary", "schematic_roundtrip_check"),
    "verify": ("run_drc", "run_erc", "run_dfm", "run_emc", "run_si", "run_thermal", "review_board", "review_project", "verify_last_action", "spice_capability", "run_spice"),
    "export": ("export_gerbers", "export_drill", "export_svg", "export_ipc2581"),
    "snapshot": ("snapshot_create", "snapshot_list", "snapshot_restore", "backend_session_info"),
    "edit": ("add_track", "move_footprint", "add_wire", "add_component", "add_custom_component"),
    "ipc": ("ipc_session_info", "ipc_board_status", "ipc_move_footprint", "pcb_backend_policy"),
}


def _routable_tools() -> dict[str, Any]:
    """Resolve the public MCP wrapper functions after module initialization."""
    return {name: globals()[f"{name}_tool"] for names in _TOOL_CATEGORIES.values() for name in names if f"{name}_tool" in globals()} | {
        "capability_report": capability_report_tool,
        "open_project": open_project,
        "datasheet_evidence": datasheet_evidence_tool,
        "compatibility_report": compatibility_report_tool,
        "get_board_status": get_board_status,
        "pcb_statistics": pcb_statistics,
        "list_footprints": list_footprints,
        "list_nets": list_nets,
        "run_drc": run_drc,
        "run_erc": run_erc,
        "export_gerbers": export_gerbers,
        "export_drill": export_drill,
        "export_svg": export_svg,
        "export_ipc2581": export_ipc2581,
        "snapshot_create": snapshot_create_tool,
        "snapshot_list": snapshot_list_tool,
        "snapshot_restore": snapshot_restore_tool,
        "add_track": add_track_tool,
        "move_footprint": move_footprint_tool,
        "verify_last_action": verify_last_action,
        "review_board": review_board_tool,
        "run_dfm": run_dfm_tool,
        "run_emc": run_emc_tool,
        "run_si": run_si_tool,
        "run_thermal": run_thermal_tool,
        "spice_capability": spice_capability_tool,
        "run_spice": run_spice_tool,
        "review_project": review_project_tool,
        "ipc_session_info": ipc_session_info_tool,
        "backend_session_info": backend_session_info_tool,
        "ipc_board_status": ipc_board_status_tool,
        "ipc_move_footprint": ipc_move_footprint_tool,
        "pcb_backend_policy": pcb_backend_policy_tool,
    }


@mcp.tool(name="list_tool_categories")
def list_tool_categories() -> dict[str, Any]:
    """List progressive-disclosure categories and the public tools in each category."""
    return {"categories": {category: list(names) for category, names in _TOOL_CATEGORIES.items()}, "total_tools": len(_routable_tools())}


@mcp.tool(name="find_tool")
def find_tool(query: str, category: str | None = None) -> dict[str, Any]:
    """Find public KiClaw tools by name, description keyword, or category."""
    needle = query.strip().lower()
    if not needle:
        raise ValueError("query must not be empty")
    categories = {category: names} if category else _TOOL_CATEGORIES
    matches = [{"name": name, "category": group} for group, names in categories.items() for name in names if needle in name.lower()]
    return {"query": query, "matches": matches, "count": len(matches)}


@mcp.tool(name="run_tool")
def run_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Dispatch one discovered public tool by name using JSON-compatible arguments."""
    tools = _routable_tools()
    if name not in tools:
        raise ValueError(f"Unknown or non-routable tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    return tools[name](**arguments)


@mcp.resource("kicad://capabilities")
def capabilities_resource() -> str:
    """Current backend capability matrix."""
    import json
    return json.dumps(capability_report(), indent=2)


@mcp.prompt()
def review_for_manufacturing(board: str) -> str:
    """A concise workflow prompt for a safe board review."""
    return f"Inspect {board}, call capability_report first, then review_project for the project-level report or review_board for one board. Treat approximate fields as estimates. Explain every finding with its source, evidence, severity, and confidence before proposing a guarded edit. Export IPC-2581 and other fabrication files only after review."


def server_version() -> str:
    return __version__
