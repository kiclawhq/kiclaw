"""Hybrid-live: auto narration attach + mutation tool registry."""

from __future__ import annotations

import os
from pathlib import Path

from kiclaw.hybrid import MUTATION_TOOLS, attach_hybrid_live
from kiclaw.visual_update import narrate_mutation


def test_mutation_tools_cover_core_edits():
    required = {
        "move_footprint",
        "add_track",
        "add_via",
        "add_wire",
        "add_component",
        "move_component",
        "ipc_move_footprint",
        "place_footprint",
        "delete_component",
    }
    assert required.issubset(MUTATION_TOOLS.keys())


def test_attach_hybrid_live_skips_non_mutations():
    raw = {"ok": True, "value": 1}
    assert attach_hybrid_live("list_footprints", {}, raw) is raw


def test_attach_hybrid_live_skips_failed_mutations():
    raw = {"ok": False, "error": "nope"}
    assert attach_hybrid_live("move_footprint", {"board": "/x.kicad_pcb"}, raw) is raw


def test_attach_hybrid_live_adds_user_message(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("KICLAW_HYBRID_NO_REFRESH", "1")
    board = tmp_path / "t.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    raw = {
        "ok": True,
        "transaction_id": "tx-test",
        "snapshot_id": "snap-test",
        "verification": {"ok": True},
        "backend": "file",
    }
    out = attach_hybrid_live(
        "move_footprint",
        {"board": str(board), "reference": "U1", "x": 10.0, "y": 20.0},
        raw,
    )
    assert out is not raw
    assert out["ok"] is True
    assert "hybrid_live" in out
    assert out["hybrid_live"]["ok"] is True
    assert "user_message" in out
    assert "U1" in out["user_message"]
    assert "Moved footprint" in out["user_message"]
    assert out["hybrid_live"].get("visual_update") is None  # refresh disabled


def test_narrate_mutation_message_shape(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("KICLAW_HYBRID_NO_REFRESH", "1")
    path = tmp_path / "b.kicad_pcb"
    path.write_text("(kicad_pcb)", encoding="utf-8")
    n = narrate_mutation(
        action="add_track",
        path=path,
        summary="Added a track.",
        look_at="F.Cu near U1",
        transaction_id="t1",
        snapshot_id="s1",
        verification_ok=True,
        backend="file",
        refresh=False,
    )
    assert n["ok"] is True
    assert "Added a track" in n["message"]
    assert "Look at" in n["message"]
    assert n["visual_update"] is None


def test_workbench_dispatch_help():
    from kiclaw.workbench import _dispatch_chat

    state: dict = {"project": None, "board": None}
    help_out = _dispatch_chat("help", state)
    assert help_out["ok"] is True
    assert "open-board" in help_out["commands"] or "open-board [PATH]" in help_out["commands"]
    assert "reload [path]" in help_out["commands"]
