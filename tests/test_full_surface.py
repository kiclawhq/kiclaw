from __future__ import annotations

from pathlib import Path

from kiclaw.edit_ext import (
    add_via,
    delete_track,
    delete_via,
    dry_run_edit,
    place_footprint,
    generate_assembly_notes,
)
from kiclaw.libraries import list_project_libraries, search_footprints, search_symbols
from kiclaw.project_session import close_project, create_new_project, get_active_project, open_project_session, save_project


FIXTURE = '''(kicad_pcb (version 20240108) (generator pcbnew)
 (general (thickness 1.6))
 (paper "A4")
 (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
 (setup (pad_to_mask_clearance 0))
 (net 0 "") (net 1 "GND") (net 2 "VCC")
 (footprint "Test:Part" (layer "F.Cu") (at 10 20 90)
  (property "Reference" "U1" (at 0 0 0) (layer "F.SilkS"))
  (property "Value" "Part" (at 0 1 0) (layer "F.Fab"))
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 2 "VCC"))
  (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 1 "GND")))
 (segment (start 1 1) (end 2 2) (width 0.25) (layer "F.Cu") (net 2))
 (via (at 3 3) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 2))
)'''


def test_create_open_save_close_project(tmp_path: Path):
    created = create_new_project(tmp_path, "FullDemo")
    assert created["ok"] is True
    assert get_active_project()["active"] is True
    assert save_project(created["path"])["ok"] is True
    assert open_project_session(created["path"])["ok"] is True
    assert close_project()["active"] is False


def test_library_search_and_project_libs(tmp_path: Path):
    created = create_new_project(tmp_path, "LibDemo")
    libs = list_project_libraries(created["path"])
    assert libs["ok"] is True
    sym = search_symbols("Resistor", limit=3)
    assert sym["ok"] is True
    # May be empty on minimal hosts without KiCad libs; don't fail hard
    fp = search_footprints("SOIC", limit=3)
    assert fp["ok"] is True


def test_place_delete_track_via_footprint(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("kiclaw.edit_ext.run_check", lambda *_: {"ok": True, "available": False})
    board = tmp_path / "b.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    assert delete_track(board, 1, 1, 2, 2)["ok"] is True
    assert delete_via(board, 3, 3)["ok"] is True
    placed = place_footprint(board, "U1", "U2", 30, 40, 0)
    assert placed["ok"] is True
    assert dry_run_edit("add_via", net_name="VCC", x=1, y=1)["dry_run"] is True


def test_assembly_notes(tmp_path: Path):
    created = create_new_project(tmp_path, "AsmDemo")
    notes = generate_assembly_notes(created["path"])
    assert notes["ok"] is True
    assert "Assembly notes" in notes["notes"]
