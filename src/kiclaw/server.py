"""The MCP surface. Domain work stays in :mod:`kiclaw.core` for testability."""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .agent_ops import get_agent_mode, get_tool_help, require_approval, set_agent_mode, suggest_next_actions
from .analysis import (
    analyze_decoupling,
    analyze_ground_strategy,
    analyze_net_clusters,
    analyze_power_tree,
    analyze_protection,
    build_analysis_context,
)
from .core import (add_component, add_custom_component, add_track, add_wire, backend_session_info, board_summary, capability_report, compatibility_report, datasheet_evidence, ipc_board_status, ipc_move_footprint, ipc_session_info, move_footprint, pcb_backend_policy, project_info, review_board, review_project, run_analysis, run_check, run_dfm, run_emc, run_export, run_si, run_spice, run_thermal, schematic_roundtrip_check, schematic_summary, spice_capability,
                   snapshot_create, snapshot_list, snapshot_restore)
from .edit_ext import (
    add_net_label,
    add_via,
    create_zone,
    delete_component,
    delete_footprint,
    delete_track,
    delete_via,
    delete_wire,
    dry_run_edit,
    fill_zones,
    generate_assembly_notes,
    lock_footprint,
    move_component,
    place_footprint,
    place_power_symbol,
    rotate_component,
    rotate_footprint,
    set_component_value,
    set_footprint_property,
    unlock_footprint,
    validate_design_rules,
)
from .inspect_ext import (
    check_connectivity,
    find_objects,
    get_component_details,
    get_design_rules,
    get_drc_errors,
    get_erc_errors,
    get_footprint_details,
    get_layer_stack,
    get_net_details,
    get_project_structure,
    get_transaction_history,
    list_components,
    list_project_files,
)
from .libraries import (
    create_project_library,
    get_footprint_info,
    get_symbol_info,
    import_footprint_to_project,
    import_symbol_to_project,
    list_footprint_libraries,
    list_project_libraries,
    list_symbol_libraries,
    search_footprints,
    search_symbols,
)
from .live import (
    get_canvas_state,
    get_selection,
    get_view_state,
    highlight_component,
    highlight_net,
    ipc_add_track,
    ipc_place_footprint,
    ipc_save_board,
    launch_kicad,
    live_status,
    open_in_kicad,
    render_board,
    select_object,
    switch_editor,
    zoom_to_object,
)
from .manufacturing import create_release_package, export_bom, export_netlist, export_pdf_schematic, export_pos
from .project_session import (
    close_project,
    create_new_project,
    get_active_project,
    open_project_session,
    save_project,
)
from .hybrid import MUTATION_TOOLS, attach_hybrid_live
from .visual_update import arrange_side_by_side, narrate_mutation, refresh_kicad_view
from .workbench import start_engineering_session

logger = logging.getLogger("kiclaw")


class KiClawMCP(FastMCP):
    """FastMCP with progress logs and automatic hybrid-live narration on mutations."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        started = time.perf_counter()
        logger.info("→ %s", name)
        try:
            # Run tool without FastMCP convert so we can attach hybrid_live to the
            # structured dict before it becomes TextContent / structured Content.
            context = self.get_context()
            raw = await self._tool_manager.call_tool(
                name, arguments or {}, context=context, convert_result=False
            )
            if name in MUTATION_TOOLS:
                try:
                    raw = attach_hybrid_live(name, arguments or {}, raw)
                except Exception:
                    logger.exception("hybrid_live attach failed for %s", name)
            tool = self._tool_manager.get_tool(name)
            if tool is not None:
                result = tool.fn_metadata.convert_result(raw)
            else:
                result = raw
        except Exception:
            logger.exception("✗ %s failed", name)
            raise
        logger.info("✓ %s (%.2fs)", name, time.perf_counter() - started)
        return result


mcp = KiClawMCP("KiClaw", instructions="Use capability_report first. File-derived board statistics are approximate; ERC/DRC and exports come from KiCad.")


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


@mcp.tool(name="run_analysis")
def run_analysis_tool(
    board: str,
    packs: list[str] | None = None,
    max_decoupling_distance_mm: float = 5.0,
    max_protection_distance_mm: float = 15.0,
    strict_connectivity: bool = False,
) -> dict[str, Any]:
    """Run deterministic deep analysis: power tree, decoupling, protection, net clusters, ground, connectivity."""
    return run_analysis(
        board,
        packs=packs,
        max_decoupling_distance_mm=max_decoupling_distance_mm,
        max_protection_distance_mm=max_protection_distance_mm,
        strict_connectivity=strict_connectivity,
    )


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


# --- Phase 2+: inspection, analysis aliases, manufacturing, edits, live, agent ---

@mcp.tool(name="list_project_files")
def list_project_files_tool(project: str) -> dict[str, Any]:
    return list_project_files(project)


@mcp.tool(name="get_project_structure")
def get_project_structure_tool(project: str) -> dict[str, Any]:
    return get_project_structure(project)


@mcp.tool(name="list_components")
def list_components_tool(schematic: str) -> dict[str, Any]:
    return list_components(schematic)


@mcp.tool(name="get_component_details")
def get_component_details_tool(schematic: str, reference: str) -> dict[str, Any]:
    return get_component_details(schematic, reference)


@mcp.tool(name="get_footprint_details")
def get_footprint_details_tool(board: str, reference: str) -> dict[str, Any]:
    return get_footprint_details(board, reference)


@mcp.tool(name="get_net_details")
def get_net_details_tool(board: str, net_name: str) -> dict[str, Any]:
    return get_net_details(board, net_name)


@mcp.tool(name="get_layer_stack")
def get_layer_stack_tool(board: str) -> dict[str, Any]:
    return get_layer_stack(board)


@mcp.tool(name="get_design_rules")
def get_design_rules_tool(board: str) -> dict[str, Any]:
    return get_design_rules(board)


@mcp.tool(name="find_objects")
def find_objects_tool(project_or_file: str, query: str, kinds: list[str] | None = None) -> dict[str, Any]:
    return find_objects(project_or_file, query, kinds)


@mcp.tool(name="get_drc_errors")
def get_drc_errors_tool(board: str) -> dict[str, Any]:
    return get_drc_errors(board)


@mcp.tool(name="get_erc_errors")
def get_erc_errors_tool(schematic: str) -> dict[str, Any]:
    return get_erc_errors(schematic)


@mcp.tool(name="check_connectivity")
def check_connectivity_tool(board: str, a: str, b: str) -> dict[str, Any]:
    return check_connectivity(board, a, b)


@mcp.tool(name="get_transaction_history")
def get_transaction_history_tool(board: str, limit: int = 20) -> dict[str, Any]:
    return get_transaction_history(board, limit)


@mcp.tool(name="analyze_power_tree")
def analyze_power_tree_tool(board: str) -> dict[str, Any]:
    return analyze_power_tree(build_analysis_context(board))


@mcp.tool(name="analyze_decoupling")
def analyze_decoupling_tool(board: str, max_distance_mm: float = 5.0) -> dict[str, Any]:
    return analyze_decoupling(build_analysis_context(board), max_distance_mm)


@mcp.tool(name="audit_protection")
def audit_protection_tool(board: str, max_distance_mm: float = 15.0) -> dict[str, Any]:
    return analyze_protection(build_analysis_context(board), max_distance_mm)


@mcp.tool(name="analyze_subcircuits")
def analyze_subcircuits_tool(board: str) -> dict[str, Any]:
    """Net-cluster based functional block hints (name conventions only)."""
    return analyze_net_clusters(build_analysis_context(board)) | {"alias": "net_clusters", "note": "Subcircuit detection is name/pattern based, not full SPICE topology."}


@mcp.tool(name="analyze_buses")
def analyze_buses_tool(board: str) -> dict[str, Any]:
    return analyze_net_clusters(build_analysis_context(board)) | {"alias": "net_clusters", "focus": "bus"}


@mcp.tool(name="analyze_passive_networks")
def analyze_passive_networks_tool(board: str) -> dict[str, Any]:
    """Passive-oriented view: decoupling pack + net clusters (triage only)."""
    ctx = build_analysis_context(board)
    return {
        "ok": True,
        "decoupling": analyze_decoupling(ctx),
        "clusters": analyze_net_clusters(ctx),
        "ground": analyze_ground_strategy(ctx),
        "disclaimer": "Passive network detection is structural triage, not SPICE extraction.",
    }


@mcp.tool(name="export_bom")
def export_bom_tool(schematic: str, output_file: str) -> dict[str, Any]:
    return export_bom(schematic, output_file)


@mcp.tool(name="export_pos")
def export_pos_tool(board: str, output_file: str, side: str = "both", units: str = "mm") -> dict[str, Any]:
    return export_pos(board, output_file, side, units)


@mcp.tool(name="export_cpl")
def export_cpl_tool(board: str, output_file: str, side: str = "both", units: str = "mm") -> dict[str, Any]:
    """Alias for export_pos (component placement / CPL)."""
    return export_pos(board, output_file, side, units)


@mcp.tool(name="export_netlist")
def export_netlist_tool(schematic: str, output_file: str, format: str = "kicadsexpr") -> dict[str, Any]:
    return export_netlist(schematic, output_file, format)


@mcp.tool(name="export_pdf_schematic")
def export_pdf_schematic_tool(schematic: str, output_file: str) -> dict[str, Any]:
    return export_pdf_schematic(schematic, output_file)


@mcp.tool(name="create_release_package")
def create_release_package_tool(project: str, output_directory: str) -> dict[str, Any]:
    return create_release_package(project, output_directory)


@mcp.tool(name="rotate_footprint")
def rotate_footprint_tool(board: str, reference: str, rotation: float, expected_sha256: str | None = None) -> dict[str, Any]:
    return rotate_footprint(board, reference, rotation, expected_sha256)


@mcp.tool(name="add_via")
def add_via_tool(board: str, net_name: str, x: float, y: float, size: float = 0.8, drill: float = 0.4, expected_sha256: str | None = None) -> dict[str, Any]:
    return add_via(board, net_name, x, y, size, drill, expected_sha256)


@mcp.tool(name="delete_footprint")
def delete_footprint_tool(board: str, reference: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return delete_footprint(board, reference, expected_sha256)


@mcp.tool(name="set_footprint_property")
def set_footprint_property_tool(board: str, reference: str, property_name: str, value: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return set_footprint_property(board, reference, property_name, value, expected_sha256)


@mcp.tool(name="add_net_label")
def add_net_label_tool(schematic: str, name: str, x: float, y: float, rotation: float = 0.0, kind: str = "label", expected_sha256: str | None = None) -> dict[str, Any]:
    return add_net_label(schematic, name, x, y, rotation, kind, expected_sha256)


@mcp.tool(name="set_component_value")
def set_component_value_tool(schematic: str, reference: str, value: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return set_component_value(schematic, reference, value, expected_sha256)


@mcp.tool(name="move_component")
def move_component_tool(schematic: str, reference: str, x: float, y: float, rotation: float | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    return move_component(schematic, reference, x, y, rotation, expected_sha256)


@mcp.tool(name="place_power_symbol")
def place_power_symbol_tool(schematic: str, power_name: str, x: float, y: float, reference: str | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    return place_power_symbol(schematic, power_name, x, y, reference, expected_sha256)


@mcp.tool(name="launch_kicad")
def launch_kicad_tool(
    project: str | None = None,
    open_board: bool = True,
    board: str | None = None,
) -> dict[str, Any]:
    """Launch KiCad GUI; by default also opens the project board in PCB Editor when found."""
    return launch_kicad(project, open_board=open_board, board=board)


@mcp.tool(name="live_status")
def live_status_tool() -> dict[str, Any]:
    return live_status()


@mcp.tool(name="render_board")
def render_board_tool(board: str, output_file: str) -> dict[str, Any]:
    return render_board(board, output_file)


@mcp.tool(name="get_selection")
def get_selection_tool() -> dict[str, Any]:
    return get_selection()


@mcp.tool(name="get_view_state")
def get_view_state_tool() -> dict[str, Any]:
    return get_view_state()


@mcp.tool(name="get_canvas_state")
def get_canvas_state_tool() -> dict[str, Any]:
    return get_canvas_state()


@mcp.tool(name="switch_editor")
def switch_editor_tool(editor: str) -> dict[str, Any]:
    return switch_editor(editor)


@mcp.tool(name="select_object")
def select_object_tool(reference: str) -> dict[str, Any]:
    return select_object(reference)


@mcp.tool(name="highlight_net")
def highlight_net_tool(net_name: str) -> dict[str, Any]:
    return highlight_net(net_name)


@mcp.tool(name="highlight_component")
def highlight_component_tool(reference: str) -> dict[str, Any]:
    return highlight_component(reference)


@mcp.tool(name="zoom_to_object")
def zoom_to_object_tool(reference: str) -> dict[str, Any]:
    return zoom_to_object(reference)


@mcp.tool(name="get_agent_mode")
def get_agent_mode_tool() -> dict[str, Any]:
    return get_agent_mode()


@mcp.tool(name="set_agent_mode")
def set_agent_mode_tool(mode: str, require_approval: bool = False) -> dict[str, Any]:
    return set_agent_mode(mode, require_approval)


@mcp.tool(name="require_approval")
def require_approval_tool(enabled: bool = True) -> dict[str, Any]:
    return require_approval(enabled)


@mcp.tool(name="get_tool_help")
def get_tool_help_tool(name: str) -> dict[str, Any]:
    return get_tool_help(name)


@mcp.tool(name="suggest_next_actions")
def suggest_next_actions_tool(project: str | None = None) -> dict[str, Any]:
    return suggest_next_actions(project)


@mcp.tool(name="start_engineering_session")
def start_engineering_session_tool(
    project: str | None = None,
    create_name: str | None = None,
    create_directory: str | None = None,
    launch: bool = True,
    mode: str = "live",
    arrange_windows: bool = True,
    open_board: bool = True,
) -> dict[str, Any]:
    """Product entry: hybrid live workbench — launch KiCad, open board, layout windows, report readiness (not full GUI puppet)."""
    return start_engineering_session(
        project,
        create_name=create_name,
        create_directory=create_directory,
        launch=launch,
        mode=mode,
        arrange_windows=arrange_windows,
        open_board=open_board,
    )


@mcp.tool(name="refresh_kicad_view")
def refresh_kicad_view_tool(
    path: str | None = None,
    kind: str = "auto",
    take_screenshot: bool = False,
    screenshot_path: str | None = None,
) -> dict[str, Any]:
    """Post-edit visual update: best-effort IPC refresh + reload guidance + optional screenshot."""
    return refresh_kicad_view(path, kind=kind, take_screenshot=take_screenshot, screenshot_path=screenshot_path)


@mcp.tool(name="narrate_mutation")
def narrate_mutation_tool(
    action: str,
    summary: str,
    path: str | None = None,
    look_at: str | None = None,
    transaction_id: str | None = None,
    snapshot_id: str | None = None,
    verification_ok: bool | None = None,
    backend: str = "file",
    refresh: bool = True,
) -> dict[str, Any]:
    """Standard post-edit agent narration: what changed, where to look, snapshot, visual update path."""
    return narrate_mutation(
        action=action,
        path=path,
        summary=summary,
        look_at=look_at,
        transaction_id=transaction_id,
        snapshot_id=snapshot_id,
        verification_ok=verification_ok,
        backend=backend,
        refresh=refresh,
    )


@mcp.tool(name="arrange_side_by_side")
def arrange_side_by_side_tool() -> dict[str, Any]:
    """Best-effort: put agent terminal on the left and KiCad on the right (macOS)."""
    return arrange_side_by_side()


@mcp.tool(name="open_in_kicad")
def open_in_kicad_tool(path: str) -> dict[str, Any]:
    """Open a .kicad_pro / .kicad_pcb / .kicad_sch (or path) in the KiCad GUI."""
    return open_in_kicad(path)


# --- Full-surface expansion: project, library, remaining edits, live extras ---

@mcp.tool(name="create_new_project")
def create_new_project_tool(directory: str, name: str, template: str | None = None) -> dict[str, Any]:
    return create_new_project(directory, name, template)


@mcp.tool(name="open_project_session")
def open_project_session_tool(path: str) -> dict[str, Any]:
    return open_project_session(path)


@mcp.tool(name="close_project")
def close_project_tool() -> dict[str, Any]:
    return close_project()


@mcp.tool(name="save_project")
def save_project_tool(path: str | None = None, backend: str = "auto") -> dict[str, Any]:
    return save_project(path, backend)


@mcp.tool(name="get_active_project")
def get_active_project_tool() -> dict[str, Any]:
    return get_active_project()


@mcp.tool(name="search_symbols")
def search_symbols_tool(query: str, limit: int = 50) -> dict[str, Any]:
    return search_symbols(query, limit)


@mcp.tool(name="search_footprints")
def search_footprints_tool(query: str, limit: int = 50) -> dict[str, Any]:
    return search_footprints(query, limit)


@mcp.tool(name="get_symbol_info")
def get_symbol_info_tool(lib_id: str) -> dict[str, Any]:
    return get_symbol_info(lib_id)


@mcp.tool(name="get_footprint_info")
def get_footprint_info_tool(fp_id: str) -> dict[str, Any]:
    return get_footprint_info(fp_id)


@mcp.tool(name="list_project_libraries")
def list_project_libraries_tool(project: str) -> dict[str, Any]:
    return list_project_libraries(project)


@mcp.tool(name="list_symbol_libraries")
def list_symbol_libraries_tool() -> dict[str, Any]:
    return list_symbol_libraries()


@mcp.tool(name="list_footprint_libraries")
def list_footprint_libraries_tool() -> dict[str, Any]:
    return list_footprint_libraries()


@mcp.tool(name="create_project_library")
def create_project_library_tool(project: str, nickname: str, kind: str = "symbol") -> dict[str, Any]:
    return create_project_library(project, nickname, kind)


@mcp.tool(name="import_symbol_to_project")
def import_symbol_to_project_tool(project: str, lib_id: str, nickname: str | None = None) -> dict[str, Any]:
    return import_symbol_to_project(project, lib_id, nickname)


@mcp.tool(name="import_footprint_to_project")
def import_footprint_to_project_tool(project: str, fp_id: str, nickname: str | None = None) -> dict[str, Any]:
    return import_footprint_to_project(project, fp_id, nickname)


@mcp.tool(name="delete_track")
def delete_track_tool(board: str, start_x: float, start_y: float, end_x: float, end_y: float, tolerance: float = 0.01, expected_sha256: str | None = None) -> dict[str, Any]:
    return delete_track(board, start_x, start_y, end_x, end_y, tolerance, expected_sha256)


@mcp.tool(name="delete_via")
def delete_via_tool(board: str, x: float, y: float, tolerance: float = 0.05, expected_sha256: str | None = None) -> dict[str, Any]:
    return delete_via(board, x, y, tolerance, expected_sha256)


@mcp.tool(name="place_footprint")
def place_footprint_tool(board: str, source_reference: str, new_reference: str, x: float, y: float, rotation: float = 0.0, value: str | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    return place_footprint(board, source_reference, new_reference, x, y, rotation, value, expected_sha256)


@mcp.tool(name="create_zone")
def create_zone_tool(board: str, net_name: str, points: list[list[float]], layer: str = "F.Cu", expected_sha256: str | None = None) -> dict[str, Any]:
    return create_zone(board, net_name, points, layer, expected_sha256)


@mcp.tool(name="fill_zones")
def fill_zones_tool(board: str) -> dict[str, Any]:
    return fill_zones(board)


@mcp.tool(name="lock_footprint")
def lock_footprint_tool(board: str, reference: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return lock_footprint(board, reference, True, expected_sha256)


@mcp.tool(name="unlock_footprint")
def unlock_footprint_tool(board: str, reference: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return unlock_footprint(board, reference, expected_sha256)


@mcp.tool(name="delete_component")
def delete_component_tool(schematic: str, reference: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return delete_component(schematic, reference, expected_sha256)


@mcp.tool(name="delete_wire")
def delete_wire_tool(schematic: str, start_x: float, start_y: float, end_x: float, end_y: float, tolerance: float = 0.01, expected_sha256: str | None = None) -> dict[str, Any]:
    return delete_wire(schematic, start_x, start_y, end_x, end_y, tolerance, expected_sha256)


@mcp.tool(name="rotate_component")
def rotate_component_tool(schematic: str, reference: str, rotation: float, expected_sha256: str | None = None) -> dict[str, Any]:
    return rotate_component(schematic, reference, rotation, expected_sha256)


@mcp.tool(name="dry_run_edit")
def dry_run_edit_tool(operation: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return dry_run_edit(operation, **(arguments or {}))


@mcp.tool(name="generate_assembly_notes")
def generate_assembly_notes_tool(project: str) -> dict[str, Any]:
    return generate_assembly_notes(project)


@mcp.tool(name="validate_design_rules")
def validate_design_rules_tool(board: str) -> dict[str, Any]:
    return validate_design_rules(board)


@mcp.tool(name="ipc_save_board")
def ipc_save_board_tool() -> dict[str, Any]:
    return ipc_save_board()


@mcp.tool(name="ipc_place_footprint")
def ipc_place_footprint_tool(board: str, reference: str, x: float, y: float, rotation: float = 0.0) -> dict[str, Any]:
    return ipc_place_footprint(board, reference, x, y, rotation)


@mcp.tool(name="ipc_add_track")
def ipc_add_track_tool(board: str, net_name: str, start_x: float, start_y: float, end_x: float, end_y: float, width: float = 0.25) -> dict[str, Any]:
    return ipc_add_track(board, net_name, start_x, start_y, end_x, end_y, width)


_TOOL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "inspect": (
        "capability_report", "compatibility_report", "open_project", "open_project_session", "project_info",
        "get_active_project", "list_project_files", "get_project_structure", "datasheet_evidence", "get_board_status",
        "pcb_statistics", "list_footprints", "list_nets", "list_components", "get_component_details",
        "get_footprint_details", "get_net_details", "get_layer_stack", "get_design_rules", "find_objects",
        "schematic_summary", "schematic_roundtrip_check", "get_transaction_history", "search_symbols",
        "search_footprints", "get_symbol_info", "get_footprint_info", "list_project_libraries",
        "list_symbol_libraries", "list_footprint_libraries",
    ),
    "verify": (
        "run_drc", "run_erc", "get_drc_errors", "get_erc_errors", "check_connectivity", "validate_design_rules",
        "run_dfm", "run_emc", "run_si", "run_thermal", "run_analysis", "analyze_power_tree", "analyze_decoupling",
        "audit_protection", "analyze_subcircuits", "analyze_buses", "analyze_passive_networks", "review_board",
        "review_project", "verify_last_action", "spice_capability", "run_spice",
    ),
    "export": (
        "export_gerbers", "export_drill", "export_svg", "export_ipc2581", "export_bom", "export_pos",
        "export_cpl", "export_netlist", "export_pdf_schematic", "create_release_package", "render_board",
        "generate_assembly_notes",
    ),
    "snapshot": ("snapshot_create", "snapshot_list", "snapshot_restore", "backend_session_info", "dry_run_edit"),
    "edit": (
        "add_track", "add_via", "delete_track", "delete_via", "move_footprint", "rotate_footprint",
        "delete_footprint", "place_footprint", "set_footprint_property", "create_zone", "fill_zones",
        "lock_footprint", "unlock_footprint", "add_wire", "delete_wire", "add_component", "add_custom_component",
        "delete_component", "add_net_label", "move_component", "rotate_component", "set_component_value",
        "place_power_symbol", "import_symbol_to_project", "import_footprint_to_project", "create_project_library",
        "create_new_project", "save_project", "close_project",
    ),
    "ipc": (
        "ipc_session_info", "ipc_board_status", "ipc_move_footprint", "ipc_place_footprint", "ipc_add_track",
        "ipc_save_board", "pcb_backend_policy", "launch_kicad", "open_in_kicad", "live_status",
        "refresh_kicad_view", "arrange_side_by_side", "get_selection", "get_view_state",
        "get_canvas_state", "switch_editor", "select_object", "highlight_net", "highlight_component",
        "zoom_to_object",
    ),
    "meta": (
        "get_agent_mode", "set_agent_mode", "require_approval", "get_tool_help", "suggest_next_actions",
        "start_engineering_session", "narrate_mutation",
    ),
}


def _routable_tools() -> dict[str, Any]:
    """Resolve the public MCP wrapper functions after module initialization."""
    tools: dict[str, Any] = {}
    for names in _TOOL_CATEGORIES.values():
        for name in names:
            if f"{name}_tool" in globals():
                tools[name] = globals()[f"{name}_tool"]
            elif name in globals():
                tools[name] = globals()[name]
    # Explicit aliases for wrappers not named *_tool
    tools.update({
        "capability_report": capability_report_tool,
        "open_project": open_project,
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
        "verify_last_action": verify_last_action,
    })
    return tools


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
    return f"Inspect {board}, call capability_report first, then run_analysis for deep structural packs (power/decoupling/protection/ground/connectivity) and review_project for the full project report (or review_board for one board). Treat approximate fields as estimates. Explain every finding with its source, evidence, severity, and confidence before proposing a guarded edit. Export IPC-2581 and other fabrication files only after review."


def server_version() -> str:
    return __version__
