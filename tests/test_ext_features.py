from __future__ import annotations

from pathlib import Path

from kiclaw.agent_ops import get_agent_mode, set_agent_mode, suggest_next_actions
from kiclaw.edit_ext import add_via, rotate_footprint, set_footprint_property
from kiclaw.inspect_ext import find_objects, get_layer_stack, get_net_details, list_project_files
from kiclaw.live import live_status


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
)'''


def test_list_project_files_and_find(tmp_path: Path):
    board = tmp_path / "x.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    (tmp_path / "x.kicad_sch").write_text("(kicad_sch (version 20250114) (generator eeschema))", encoding="utf-8")
    files = list_project_files(tmp_path)
    assert files["ok"] is True
    assert files["counts"]["boards"] == 1
    found = find_objects(tmp_path, "VCC", kinds=["net"])
    assert found["count"] >= 1


def test_layer_stack_and_net_details(tmp_path: Path):
    board = tmp_path / "x.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    layers = get_layer_stack(board)
    assert layers["ok"] is True
    assert layers["copper_layer_count"] >= 1
    details = get_net_details(board, "VCC")
    assert details["ok"] is True
    assert details["attachments"]


def test_pcb_edit_via_rotate_property(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("kiclaw.edit_ext.run_check", lambda *_: {"ok": True, "available": False})
    board = tmp_path / "x.kicad_pcb"
    board.write_text(FIXTURE, encoding="utf-8")
    via = add_via(board, "VCC", 5, 5)
    assert via["ok"] is True
    rot = rotate_footprint(board, "U1", 45)
    assert rot["ok"] is True
    prop = set_footprint_property(board, "U1", "Value", "MCU")
    assert prop["ok"] is True


def test_agent_mode_and_live_status():
    assert set_agent_mode("inspect")["ok"] is True
    assert get_agent_mode()["mode"] == "inspect"
    status = live_status()
    assert status["ok"] is True
    assert "instructions" in status
    suggestions = suggest_next_actions()
    assert suggestions["suggestions"]
