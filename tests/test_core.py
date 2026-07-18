from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from kiclaw.core import (KiClawConflictError, KiClawError, add_component, add_custom_component, add_track, add_wire, backend_session_info, begin_transaction,
                         board_summary, capability_report, ipc_board_status, ipc_move_footprint, move_footprint, pin_backend,
                         review_board, review_project, schematic_roundtrip_check, schematic_summary, snapshot_create, snapshot_restore)


FIXTURE = '''(kicad_pcb (version 20240108) (generator pcbnew)
 (general (thickness 1.6))
 (paper "A4")
 (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.Silkscreen") (37 "F.SilkS" user "f.Silkscreen") (44 "Edge.Cuts" user))
 (setup (pad_to_mask_clearance 0))
 (net 0 "") (net 1 "VCC")
 (footprint "Test:Part" (layer "F.Cu") (at 10 20 90)
  (property "Reference" "U1" (at 0 0 0) (layer "F.SilkS"))
  (property "Value" "Part" (at 0 1 0) (layer "F.Fab")))
)'''


def test_capability_detects_macos_cli():
    report = capability_report()
    assert report["file_backend"]["available"] is True
    assert report["kicad_cli"]["available"] is True
    assert report["kicad_cli"]["version"]


def test_summary_and_guarded_edit_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("kiclaw.core.run_check", lambda *_: {"ok": True, "available": False})
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    before = board_summary(board)
    assert before["statistics"] == {"footprints": 1, "nets": 1, "tracks": 0, "vias": 0, "zones": 0}
    manual = snapshot_create(board, "original")
    action = add_track(board, "VCC", 1, 1, 2, 2)
    assert action["ok"] is True
    assert action["diff"]["statistics"]["tracks"] == 1
    snapshot_restore(board, manual["id"])
    assert board_summary(board)["statistics"]["tracks"] == 0
    action = move_footprint(board, "U1", 33, 44)
    assert action["ok"] is True
    assert board_summary(board)["footprints"][0]["at"][:2] == [33.0, 44.0]


def test_mutation_input_and_snapshot_id_are_guarded(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("kiclaw.core.run_check", lambda *_: {"ok": True, "available": False})
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    snapshot = snapshot_create(board, "unsafe label/with spaces")
    assert "/" not in snapshot["id"]
    with pytest.raises(KiClawError, match="Invalid snapshot id"):
        snapshot_restore(board, "../escape")
    with pytest.raises(KiClawError, match="finite"):
        add_track(board, "VCC", float("nan"), 0, 1, 1)


def test_stale_expected_hash_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("kiclaw.core.run_check", lambda *_: {"ok": True, "available": False})
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    expected = board_summary(board)["sha256"]
    board.write_text(FIXTURE + "\n", encoding="utf-8")
    with pytest.raises(KiClawConflictError, match="Stale board hash"):
        add_track(board, "VCC", 1, 1, 2, 2, expected_sha256=expected)


def test_failed_post_write_validation_rolls_back(tmp_path: Path):
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    transaction = begin_transaction(board, "test_failure")
    transaction.take_snapshot("before-failure")
    def fail(_: dict) -> None:
        raise KiClawError("verification failed")
    with pytest.raises(KiClawError, match="verification"):
        transaction.commit(FIXTURE + "\n(segment invalid)", fail)
    assert board.read_text(encoding="utf-8") == FIXTURE
    manifest = transaction.manifest_path.read_text(encoding="utf-8")
    assert '"status": "rolled_back"' in manifest


def test_backend_session_is_pinned(tmp_path: Path):
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    session = pin_backend(board, "file")
    assert backend_session_info(board)["session_id"] == session["session_id"]
    with pytest.raises(KiClawConflictError, match="pinned"):
        pin_backend(board, "ipc")


def test_ipc_probe_is_honest():
    status = ipc_board_status()
    assert status["backend"] == "ipc"
    if status["ok"]:
        assert status["approximate"] is False
        assert "statistics" in status
    else:
        assert "capability" in status


def test_ipc_mutator_reports_disabled_session_without_touching_disk(tmp_path: Path, monkeypatch):
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    before = board.read_text(encoding="utf-8")
    monkeypatch.setattr("kiclaw.core.ipc_capability", lambda: {
        "available": False, "binding": "kicad-python/kipy", "binding_available": True,
        "connection_available": False, "reason": "test-disabled", "limitations": "test",
    })
    result = ipc_move_footprint(board, "U1", 33, 44)
    assert result["ok"] is False
    assert result["backend"] == "ipc"
    assert result["available"] is False
    assert "enable KiCad's API Server" in result["reason"]
    assert board.read_text(encoding="utf-8") == before


def test_ipc_mutator_uses_native_undo_commit_and_manifest(tmp_path: Path, monkeypatch):
    board_path = tmp_path / "test.kicad_pcb"
    board_path.write_text(FIXTURE, encoding="utf-8")

    class Point:
        def __init__(self, x: int, y: int):
            self.x, self.y = x, y

    class Text:
        def __init__(self, value: str):
            self.value = value

    class Field:
        def __init__(self, value: str):
            self.text = Text(value)

    class Angle:
        def __init__(self, degrees: float):
            self.degrees = degrees

        @classmethod
        def from_degrees(cls, degrees: float):
            return cls(degrees)

    class Vector2:
        def __init__(self, x: int, y: int):
            self.x, self.y = x, y

        @classmethod
        def from_xy_mm(cls, x: float, y: float):
            return cls(round(x * 1_000_000), round(y * 1_000_000))

    class Footprint:
        def __init__(self):
            self.reference_field = Field("U1")
            self.position = Point(10_000_000, 20_000_000)
            self.orientation = Angle(90)

    class Board:
        def __init__(self):
            self.name = str(board_path)
            self.footprint = Footprint()
            self.pushed = False

        def get_footprints(self):
            return [self.footprint]

        def begin_commit(self):
            return object()

        def update_items(self, item):
            self.updated = item

        def push_commit(self, commit, message):
            self.pushed = message

        def drop_commit(self, commit):
            raise AssertionError("commit should not be dropped")

    live_board = Board()

    class KiCad:
        def __init__(self, **kwargs):
            pass

        def ping(self):
            pass

        def get_board(self):
            return live_board

    kipy_module = types.ModuleType("kipy")
    kipy_module.KiCad = KiCad
    geometry_module = types.ModuleType("kipy.geometry")
    geometry_module.Angle = Angle
    geometry_module.Vector2 = Vector2
    monkeypatch.setitem(sys.modules, "kipy", kipy_module)
    monkeypatch.setitem(sys.modules, "kipy.geometry", geometry_module)
    monkeypatch.setattr("kiclaw.core.ipc_capability", lambda: {
        "available": True, "binding": "kicad-python/kipy", "binding_available": True,
        "connection_available": True, "board_api_available": True, "reason": "test-live", "limitations": "test",
    })

    result = ipc_move_footprint(board_path, "U1", 33, 44, 12)
    assert result["ok"] is True
    assert result["saved_to_disk"] is False
    assert result["undoable_in_kicad"] is True
    assert live_board.pushed == "KiClaw move footprint U1"
    assert [live_board.footprint.position.x, live_board.footprint.position.y] == [33_000_000, 44_000_000]
    assert live_board.footprint.orientation.degrees == 12
    manifest = next((tmp_path / ".kiclaw" / "transactions").glob("*.json")).read_text(encoding="utf-8")
    assert '"status": "committed-live"' in manifest


def test_deterministic_review_reports_missing_outline(tmp_path: Path, monkeypatch):
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    monkeypatch.setattr("kiclaw.core.run_check", lambda *_: {"ok": True, "available": True, "report": {"violations": [], "unconnected_items": []}})
    result = review_board(board)
    assert result["ok"] is False
    assert result["finding_counts"]["error"] == 1
    assert result["findings"][0]["evidence"].startswith("KiClaw deterministic")


def test_project_review_returns_machine_readable_report(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.kicad_pcb").write_text(FIXTURE, encoding="utf-8")
    (project / "main.kicad_sch").write_text("(kicad_sch (version 20231120) (generator eeschema))", encoding="utf-8")
    monkeypatch.setattr("kiclaw.core.run_check", lambda kind, *_: {"ok": True, "available": True, "kind": kind, "report": {"violations": [], "unconnected_items": []}})
    result = review_project(project)
    assert result["project"]["boards"]
    assert result["project"]["schematics"]
    assert isinstance(result["findings"], list)


def test_schematic_roundtrip_check_is_byte_exact_on_real_template():
    schematic = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/stm32f100-discovery-shield/stm32f100-discovery-shield.kicad_sch")
    if not schematic.exists():
        return
    summary = schematic_summary(schematic)
    result = schematic_roundtrip_check(schematic)
    assert summary["root"] == "kicad_sch"
    assert summary["byte_length"] > 1000
    assert result["ok"] is True
    assert result["round_trip"]["bytes_changed"] == 0
    assert result["mutation_ready"] is False


def test_schematic_roundtrip_rejects_unbalanced_input(tmp_path: Path):
    schematic = tmp_path / "broken.kicad_sch"
    schematic.write_text("(kicad_sch (version 20250114)", encoding="utf-8")
    with pytest.raises(KiClawError, match="Unbalanced"):
        schematic_roundtrip_check(schematic)


def test_add_wire_is_guarded_and_round_trip_verified(tmp_path: Path):
    source = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/stm32f100-discovery-shield/stm32f100-discovery-shield.kicad_sch")
    if not source.exists():
        return
    schematic = tmp_path / source.name
    shutil.copy2(source, schematic)
    before = schematic_summary(schematic)
    result = add_wire(schematic, 100, 100, 110, 100)
    assert result["ok"] is True
    assert result["diff"]["top_level_counts"]["wire"] == 1
    assert result["verification"]["round_trip"]["ok"] is True
    assert schematic_summary(schematic)["top_level_counts"]["wire"] == before["top_level_counts"]["wire"] + 1


def test_add_wire_rejects_stale_hash(tmp_path: Path):
    schematic = tmp_path / "test.kicad_sch"
    schematic.write_text("(kicad_sch (version 20250114) (generator eeschema) (sheet_instances))", encoding="utf-8")
    expected = schematic_summary(schematic)["sha256"]
    schematic.write_text(schematic.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(KiClawConflictError, match="Stale schematic hash"):
        add_wire(schematic, 1, 1, 2, 2, expected_sha256=expected)


def test_add_component_clones_existing_symbol_with_fresh_uuids(tmp_path: Path):
    source = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/stm32f100-discovery-shield/stm32f100-discovery-shield.kicad_sch")
    if not source.exists():
        return
    schematic = tmp_path / source.name
    shutil.copy2(source, schematic)
    result = add_component(schematic, "Connector_Generic:Conn_01x28", "P4", 240, 50, "TEST", 0)
    assert result["ok"] is True
    assert result["diff"]["top_level_counts"]["symbol"] == 1
    assert result["verification"]["round_trip"]["ok"] is True
    assert result["verification"]["erc"]["ok"] is True


def test_add_component_rejects_unknown_library_id(tmp_path: Path):
    source = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/stm32f100-discovery-shield/stm32f100-discovery-shield.kicad_sch")
    if not source.exists():
        return
    schematic = tmp_path / source.name
    shutil.copy2(source, schematic)
    with pytest.raises(KiClawError, match="custom library insertion"):
        add_component(schematic, "Example:Missing", "P4", 240, 50)


def test_add_custom_component_generates_project_library_and_native_loads(tmp_path: Path):
    source = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/stm32f100-discovery-shield")
    if not source.exists():
        return
    project = tmp_path / "project"
    shutil.copytree(source, project)
    schematic = project / "stm32f100-discovery-shield.kicad_sch"
    result = add_custom_component(schematic, "Connector_Generic:Conn_01x28", "KiClaw:CustomHeader28", "P4", 240, 50, "CUSTOM", 0)
    assert result["ok"] is True
    assert Path(result["library"]["path"]).is_file()
    assert Path(result["library"]["table"]).is_file()
    assert result["verification"]["erc"]["exit_code"] != 3
    assert "Failed to load schematic" not in result["verification"]["erc"]["stderr"]


def test_progressive_tool_router_lists_searches_and_dispatches(tmp_path: Path):
    from kiclaw.server import find_tool, list_tool_categories, run_tool
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    categories = list_tool_categories()
    assert categories["total_tools"] >= 32
    assert "add_custom_component" in categories["categories"]["edit"]
    assert any(match["name"] == "run_dfm" for match in find_tool("dfm")["matches"])
    result = run_tool("pcb_statistics", {"board": str(board)})
    assert result["footprints"] == 1


def test_pcb_backend_policy_is_non_mutating_and_explicit(tmp_path: Path):
    from kiclaw.core import pcb_backend_policy
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    before = board.read_bytes()
    result = pcb_backend_policy(board, "auto")
    assert result["ok"] is True
    assert result["selected"] in {"ipc", "file"}
    assert board.read_bytes() == before


def test_datasheet_evidence_hashes_source_and_scores_explicit_claims(tmp_path: Path):
    from kiclaw.core import datasheet_evidence
    source = tmp_path / "part-datasheet.txt"
    source.write_text("Operating temperature: -40 C to 85 C\nMaximum voltage: 5 V\n", encoding="utf-8")
    result = datasheet_evidence(str(source), ["-40 C to 85 C", "10 V"])
    assert result["ok"] is True
    assert result["source_kind"] == "file"
    assert result["bytes"] > 0
    assert len(result["sha256"]) == 64
    assert result["confidence"] == "medium"
    assert result["claims"] == [{"claim": "-40 C to 85 C", "found": True}, {"claim": "10 V", "found": False}]


def test_compatibility_report_is_machine_readable():
    from kiclaw.core import compatibility_report
    result = compatibility_report()
    assert result["ok"] is True
    assert result["kicad_version"]
    assert result["checks"]["file_backend"]["status"] == "pass"


def test_emc_profile_is_conservative_and_integrated(tmp_path: Path):
    from kiclaw.core import review_board, run_emc
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    result = run_emc(board)
    assert result["ok"] is True
    assert result["finding_counts"].get("warning", 0) >= 1
    assert "lab testing" in result["disclaimer"]


def test_spice_reports_unavailable_without_ngspice(tmp_path: Path, monkeypatch):
    from kiclaw.core import run_spice, spice_capability
    netlist = tmp_path / "test.cir"
    netlist.write_text(".end\n", encoding="utf-8")
    monkeypatch.setattr("kiclaw.core.find_ngspice", lambda: None)
    assert spice_capability()["available"] is False
    result = run_spice(netlist)
    assert result["ok"] is False
    assert result["available"] is False
    assert "ngspice" in result["reason"]


def test_si_and_thermal_profiles_are_non_blocking_indicators(tmp_path: Path):
    from kiclaw.core import run_si, run_thermal
    board = tmp_path / "test.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    si = run_si(board)
    thermal = run_thermal(board)
    assert si["ok"] is True
    assert thermal["ok"] is True
    assert "impedance" in si["disclaimer"]
    assert "junction temperature" in thermal["disclaimer"]


def test_real_cli_drc_on_installed_template(tmp_path: Path):
    from kiclaw.core import run_check
    source = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/EuroCard160mmX100mm/EuroCard160mmX100mm.kicad_pcb")
    if not source.exists():
        return
    result = run_check("drc", source)
    assert result["available"] is True
    assert result["report"] is not None


def test_native_mutation_and_exports_on_real_project():
    from kiclaw.core import run_export

    source = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/EuroCard160mmX100mm")
    if not source.exists():
        return
    with TemporaryDirectory(prefix="kiclaw-test-project-") as root:
        project = Path(root) / source.name
        shutil.copytree(source, project)
        board = project / "EuroCard160mmX100mm.kicad_pcb"
        summary = board_summary(board)
        original = summary["footprints"][0]["at"]
        action = move_footprint(board, summary["footprints"][0]["reference"], original[0] + 0.1, original[1])
        assert action["ok"] is True
        assert action["verification"]["ok"] is True
        project_review = review_project(project)
        assert project_review["ok"] is True
        assert "finding_counts" in project_review
        with TemporaryDirectory(prefix="kiclaw-test-exports-") as output:
            root_out = Path(output)
            for kind in ("gerbers", "drill"):
                result = run_export(kind, board, root_out / kind)
                assert result["ok"] is True
                assert result["files"]
            ipc = run_export("ipc2581", board, root_out / "board.xml")
            assert ipc["ok"] is True
            assert (root_out / "board.xml").is_file()
            svg = run_export("svg", board, root_out / "board.svg")
            assert svg["ok"] is True
            assert (root_out / "board.svg").is_file()
