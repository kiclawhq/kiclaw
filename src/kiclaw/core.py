"""KiCad discovery, safe file operations, and approximate board inspection."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

MACOS_KICAD_CLI = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")


class KiClawError(ValueError):
    """A safe, user-facing KiClaw error."""


class KiClawConflictError(KiClawError):
    """The board changed since an action began or since the caller's hash."""


def resolve_path(value: str | Path, suffix: str | None = None) -> Path:
    path = Path(value).expanduser().resolve()
    if suffix and path.suffix != suffix:
        raise KiClawError(f"Expected a {suffix} file, got: {path}")
    return path


def find_kicad_cli() -> Path | None:
    configured = os.environ.get("KICLAW_KICAD_CLI")
    candidates = [Path(configured)] if configured else []
    candidates += [Path(item) for item in (shutil.which("kicad-cli"),) if item]
    candidates += [MACOS_KICAD_CLI]
    candidates += [
        Path("C:/Program Files/KiCad/bin/kicad-cli.exe"),
        Path("/usr/bin/kicad-cli"),
        Path("/usr/local/bin/kicad-cli"),
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_ngspice() -> Path | None:
    """Locate an ngspice executable without requiring it as a KiClaw dependency."""
    configured = os.environ.get("KICLAW_NGSPICE")
    candidates = [Path(configured)] if configured else []
    candidates += [Path(item) for item in (shutil.which("ngspice"),) if item]
    candidates += [Path("/usr/local/bin/ngspice"), Path("/opt/homebrew/bin/ngspice")]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def spice_capability() -> dict[str, Any]:
    cli = find_ngspice()
    version = None
    if cli:
        try:
            result = subprocess.run([str(cli), "-v"], text=True, capture_output=True, check=False, timeout=10)
            version = (result.stdout or result.stderr).strip().splitlines()[0] if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            version = None
    return {"available": cli is not None, "path": str(cli) if cli else None, "version": version, "mode": "batch" if cli else None}


def run_spice(netlist: str | Path, timeout: int = 120) -> dict[str, Any]:
    """Run a supplied SPICE netlist in batch mode when ngspice is installed."""
    path = resolve_path(netlist)
    if not path.is_file():
        raise KiClawError(f"SPICE netlist not found: {path}")
    if timeout <= 0 or timeout > 600:
        raise KiClawError("timeout must be between 1 and 600 seconds")
    capability = spice_capability()
    if not capability["available"]:
        return {"ok": False, "available": False, "netlist": str(path), "capability": capability,
                "reason": "ngspice was not found; install it or set KICLAW_NGSPICE"}
    with tempfile.TemporaryDirectory(prefix="kiclaw-spice-") as directory:
        report = Path(directory) / "ngspice-report.txt"
        command = [str(find_ngspice()), "-b", "-o", str(report), str(path)]
        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout, cwd=str(path.parent))
        except subprocess.TimeoutExpired as exc:
            return {"ok": False, "available": True, "netlist": str(path), "timed_out": True, "capability": capability,
                    "reason": f"ngspice exceeded {timeout} seconds", "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""}
    report_text = report.read_text(encoding="utf-8", errors="replace") if report.exists() else ""
    return {"ok": completed.returncode == 0, "available": True, "netlist": str(path), "exit_code": completed.returncode,
            "capability": capability, "report": report_text, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(),
            "evidence": "ngspice batch exit status and captured report; interpret circuit results separately."}


def _has_headless_ipc_server(cli: Path | None) -> bool:
    if not cli:
        return False
    try:
        result = subprocess.run([str(cli), "api-server", "--help"], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0 and "api-server" in (result.stdout + result.stderr)
    except (OSError, subprocess.TimeoutExpired):
        return False


def ipc_capability(cli: Path | None = None) -> dict[str, Any]:
    """Describe the official IPC boundary without silently opening a session."""
    cli = cli or find_kicad_cli()
    socket_path = os.environ.get("KICAD_API_SOCKET")
    token_configured = bool(os.environ.get("KICAD_API_TOKEN"))
    try:
        import importlib.util
        binding_available = importlib.util.find_spec("kipy") is not None
    except (ImportError, ValueError):
        binding_available = False
    headless = _has_headless_ipc_server(cli)
    connection_available = False
    board_api_available = False
    open_documents: list[dict[str, Any]] = []
    board_api_error = None
    api_version = None
    connection_error = None
    if binding_available:
        try:
            from kipy import KiCad
            connection = KiCad(timeout_ms=500)
            connection.ping()
            api_version = str(connection.get_version())
            connection_available = True
            try:
                from kipy.proto.common.types import DocumentType
                documents = connection.get_open_documents(DocumentType.DOCTYPE_PCB)
                board_api_available = True
                open_documents = [{"board_filename": document.board_filename, "type": int(document.type)} for document in documents]
            except Exception as exc:
                board_api_error = f"{type(exc).__name__}: {exc}"
            del connection
        except Exception as exc:  # kipy has version-specific exception classes.
            connection_error = f"{type(exc).__name__}: {exc}"
    if not binding_available:
        reason = "Install the optional 'ipc' extra (kicad-python) to use the official IPC bindings."
    elif connection_available and board_api_available:
        reason = "Connected to a running KiCad IPC API session during the capability probe."
    elif connection_available:
        reason = f"Connected to KiCad IPC, but the PCB document API is unavailable: {board_api_error}"
    elif socket_path:
        reason = f"KiCad advertised an IPC socket, but the connection probe failed: {connection_error}"
    elif headless:
        reason = "KiCad can provide a headless API server; no session is started during capability detection."
    else:
        reason = f"No reachable IPC session: {connection_error or 'KICAD_API_SOCKET is not present and no headless API server is available.'}"
    return {
        "available": connection_available,
        "binding": "kicad-python/kipy",
        "binding_available": binding_available,
        "connection_available": connection_available,
        "board_api_available": board_api_available,
        "open_documents": open_documents,
        "board_api_error": board_api_error,
        "api_version": api_version,
        "socket_path": socket_path,
        "token_configured": token_configured,
        "headless_api_server": headless,
        "reason": reason,
        "limitations": "IPC is PCB-focused on KiCad 9/10; schematic and export operations remain file/CLI backed.",
    }


def ipc_session_info() -> dict[str, Any]:
    """Read-only probe of the live IPC session and open PCB documents."""
    capability = ipc_capability()
    if not capability["available"]:
        return {"ok": False, "capability": capability}
    if not capability.get("board_api_available"):
        return {"ok": False, "capability": capability,
                "reason": "KiCad IPC is connected, but no PCB Editor document API is available. Open a board in PCB Editor and retry."}
    try:
        from kipy import KiCad
        from kipy.proto.common.types import DocumentType
        connection = KiCad(timeout_ms=1000)
        version = str(connection.get_version())
        documents = connection.get_open_documents(DocumentType.DOCTYPE_PCB)
        return {"ok": True, "version": version, "documents": [
            {"board_filename": document.board_filename, "type": int(document.type)} for document in documents
        ], "capability": capability}
    except Exception as exc:
        return {"ok": False, "capability": capability, "reason": f"{type(exc).__name__}: {exc}"}


def ipc_board_status() -> dict[str, Any]:
    """Read the active PCB through the official IPC API (never a file parse)."""
    capability = ipc_capability()
    if not capability["available"]:
        return {"ok": False, "backend": "ipc", "capability": capability}
    if not capability.get("board_api_available"):
        return {"ok": False, "backend": "ipc", "capability": capability,
                "reason": "KiCad IPC is connected, but no PCB Editor document API is available. Open a board in PCB Editor and retry."}
    try:
        from kipy import KiCad
        from kipy.util import to_mm
        connection = KiCad(timeout_ms=1000)
        connection.ping()
        board = connection.get_board()
        footprints = board.get_footprints()
        nets = board.get_nets()
        return {
            "ok": True,
            "backend": "ipc",
            "version": str(connection.get_version()),
            "board": board.name,
            "approximate": False,
            "footprints": [{
                "reference": footprint.reference_field.text.value,
                "value": footprint.value_field.text.value,
                "at": [to_mm(footprint.position.x), to_mm(footprint.position.y)],
                "rotation": footprint.orientation.degrees,
            } for footprint in footprints],
            "nets": [{"name": net.name} for net in nets],
            "statistics": {"footprints": len(footprints), "nets": len(nets),
                            "tracks": len(board.get_tracks()), "vias": len(board.get_vias()),
                            "zones": len(board.get_zones())},
            "capability": capability,
        }
    except Exception as exc:
        return {"ok": False, "backend": "ipc", "capability": capability,
                "reason": f"{type(exc).__name__}: {exc}"}


def ipc_move_footprint(
    board: str | Path,
    reference: str,
    x: float,
    y: float,
    rotation: float | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Move a footprint in the active KiCad PCB through IPC.

    This intentionally edits the live KiCad document and leaves saving explicit.  A
    disk snapshot and transaction manifest are created before the edit, while the
    native KiCad commit makes the live edit one undoable operation.  We refuse to
    act unless the requested board is the active IPC document.
    """
    if not all(math.isfinite(value) for value in (x, y)) or (rotation is not None and not math.isfinite(rotation)):
        raise KiClawError("footprint position and rotation must be finite numbers")
    path = resolve_path(board, ".kicad_pcb")
    if not path.is_file():
        raise KiClawError(f"Board not found: {path}")
    capability = ipc_capability()
    if not capability["available"]:
        return {"ok": False, "backend": "ipc", "available": False, "capability": capability,
                "reason": "No live KiCad IPC session is available; enable KiCad's API Server and retry."}
    if not capability.get("board_api_available"):
        return {"ok": False, "backend": "ipc", "available": False, "capability": capability,
                "reason": "KiCad IPC is connected, but no PCB Editor document API is available. Open a board in PCB Editor and retry."}
    current_sha256 = sha256(path)
    if expected_sha256 and expected_sha256 != current_sha256:
        raise KiClawConflictError(f"Stale board hash: expected {expected_sha256}, found {current_sha256}.")
    transaction: BoardTransaction | None = None
    try:
        from kipy import KiCad
        from kipy.geometry import Angle, Vector2

        connection = KiCad(timeout_ms=1500)
        connection.ping()
        live_board = connection.get_board()
        live_name = Path(str(live_board.name)).expanduser()
        if not live_name.is_absolute():
            live_name = (path.parent / live_name).resolve()
        else:
            live_name = live_name.resolve()
        if live_name != path:
            return {"ok": False, "backend": "ipc", "available": True, "capability": capability,
                    "reason": f"Active KiCad board is {live_name}, not the requested {path}."}

        footprints = list(live_board.get_footprints())
        selected = next((item for item in footprints if item.reference_field.text.value == reference), None)
        if selected is None:
            raise KiClawError(f"Footprint reference not found in active board: {reference}")
        before_position = [selected.position.x / 1_000_000, selected.position.y / 1_000_000]
        before_rotation = selected.orientation.degrees
        transaction = begin_transaction(path, "ipc_move_footprint", current_sha256, backend="ipc")
        disk_snapshot = transaction.take_snapshot("before-ipc-move-footprint")
        commit = live_board.begin_commit()
        try:
            selected.position = Vector2.from_xy_mm(x, y)
            if rotation is not None:
                selected.orientation = Angle.from_degrees(rotation)
            live_board.update_items(selected)
            live_board.push_commit(commit, f"KiClaw move footprint {reference}")
        except Exception:
            live_board.drop_commit(commit)
            raise
        after_position = [selected.position.x / 1_000_000, selected.position.y / 1_000_000]
        after_rotation = selected.orientation.degrees
        transaction.status = "committed-live"
        transaction.persist(
            after_sha256=sha256(path),
            after_live={"reference": reference, "at": after_position, "rotation": after_rotation},
            saved_to_disk=False,
            snapshot=disk_snapshot,
        )
        return {
            "ok": True,
            "backend": "ipc",
            "transaction_id": transaction.transaction_id,
            "session_id": transaction.session_id,
            "snapshot_id": disk_snapshot["id"],
            "board": str(path),
            "reference": reference,
            "before": {"at": before_position, "rotation": before_rotation},
            "after": {"at": after_position, "rotation": after_rotation},
            "saved_to_disk": False,
            "undoable_in_kicad": True,
            "note": "The live document changed; save it in KiCad (or use a future explicit save tool) to persist it.",
            "capability": capability,
        }
    except KiClawError as exc:
        if transaction is not None and transaction.status == "pending":
            transaction.status = "rolled_back"
            transaction.persist(error=str(exc))
        raise
    except Exception as exc:
        if transaction is not None and transaction.status == "pending":
            transaction.status = "rolled_back"
            transaction.persist(error=str(exc))
        return {"ok": False, "backend": "ipc", "available": True, "capability": capability,
                "reason": f"{type(exc).__name__}: {exc}"}


def capability_report() -> dict[str, Any]:
    cli = find_kicad_cli()
    version = None
    if cli:
        try:
            result = subprocess.run([str(cli), "version"], text=True, capture_output=True, check=False, timeout=10)
            version = result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            version = None
    ipc = ipc_capability(cli)
    return {
        "kicad_cli": {"available": cli is not None, "path": str(cli) if cli else None, "version": version},
        "file_backend": {"available": True, "limitations": "Statistics are parsed from KiCad S-expressions and marked approximate."},
        "pcbnew": {"available": False, "reason": "Not probed in v0.1; use kicad-cli or file backend."},
        "ipc": ipc,
        "pcb_backend_policy": {
            "preferred": "ipc",
            "fallback": "file",
            "selected_for_auto": "ipc" if ipc.get("available") and ipc.get("board_api_available") else "file",
            "selection_rule": "Use IPC only when a live PCB Editor document API is available; otherwise use guarded file/CLI operations.",
        },
    }


def pcb_backend_policy(board: str | Path | None = None, requested: str = "auto") -> dict[str, Any]:
    """Select the PCB backend without mutating a document."""
    if requested not in {"auto", "ipc", "file"}:
        raise KiClawError("requested backend must be auto, ipc, or file")
    capability = ipc_capability()
    selected = "file"
    reason = "File/CLI backend is always available and preserves explicit disk persistence."
    if requested in {"auto", "ipc"} and capability.get("available") and capability.get("board_api_available"):
        selected = "ipc"
        reason = "Live KiCad PCB Editor IPC is available."
    elif requested == "ipc":
        return {"ok": False, "requested": requested, "selected": None, "reason": "Requested IPC backend is unavailable.", "capability": capability}
    result: dict[str, Any] = {"ok": True, "requested": requested, "selected": selected, "reason": reason, "capability": capability}
    if board is not None:
        result["board"] = str(resolve_path(board, ".kicad_pcb"))
    return result


def compatibility_report(project: str | Path | None = None) -> dict[str, Any]:
    """Build a conservative KiCad/backend compatibility matrix for this host."""
    capabilities = capability_report()
    checks: dict[str, Any] = {
        "kicad_cli_detected": {"status": "pass" if capabilities["kicad_cli"]["available"] else "unavailable", "version": capabilities["kicad_cli"]["version"]},
        "file_backend": {"status": "pass"},
        "ipc_backend": {"status": "pass" if capabilities["ipc"].get("available") else "unavailable", "board_api_available": capabilities["ipc"].get("board_api_available", False)},
        "gerber_export": {"status": "pass" if capabilities["kicad_cli"]["available"] else "unavailable", "verification": "CLI detected; run_export validates a concrete board"},
        "ipc2581_export": {"status": "pass" if capabilities["kicad_cli"]["available"] else "unavailable", "verification": "CLI detected; run_export validates a concrete board"},
    }
    project_info_result = None
    if project is not None:
        project_info_result = project_info(project)
        board_checks = []
        for board in project_info_result["boards"]:
            drc = run_check("drc", board)
            board_checks.append({"path": board, "drc": {"status": "pass" if drc.get("ok") else "fail", "exit_code": drc.get("exit_code"), "issues": drc.get("issues")}})
        schematic_checks = []
        for schematic in project_info_result["schematics"]:
            erc = run_check("erc", schematic)
            schematic_checks.append({"path": schematic, "erc": {"status": "pass" if erc.get("ok") else "fail", "exit_code": erc.get("exit_code"), "issues": erc.get("issues")}})
        checks["native_project_checks"] = {"status": "pass" if all(item["drc"]["status"] == "pass" for item in board_checks) and all(item["erc"]["status"] == "pass" for item in schematic_checks) else "fail", "boards": board_checks, "schematics": schematic_checks}
    return {"ok": True, "kicad_version": capabilities["kicad_cli"]["version"], "project": project_info_result, "checks": checks, "disclaimer": "Statuses describe this host and supplied fixtures only; they are not a substitute for a multi-version compatibility lab."}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count(text: str, keyword: str) -> int:
    return len(re.findall(rf"\({re.escape(keyword)}(?:\s|\))", text))


def _top_level_forms(text: str, keyword: str) -> list[str]:
    """Return complete S-expression forms for a keyword without depending on a KiCad binding."""
    matches = list(re.finditer(rf"\({re.escape(keyword)}(?:\s|\))", text))
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


def board_summary(board: str | Path) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    if not path.is_file():
        raise KiClawError(f"Board not found: {path}")
    text = path.read_text(encoding="utf-8")
    footprints = []
    for form in _top_level_forms(text, "footprint"):
        ref = re.search(r'\(property "Reference" "([^"]*)"', form)
        value = re.search(r'\(property "Value" "([^"]*)"', form)
        at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", form)
        footprints.append({"reference": ref.group(1) if ref else None, "value": value.group(1) if value else None,
                           "at": [float(v) for v in at.groups(default="0")] if at else None})
    nets = [{"id": int(item[0]), "name": item[1]} for item in re.findall(r'\(net\s+(\d+)\s+"([^"]*)"\)', text)]
    return {
        "path": str(path), "sha256": sha256(path), "approximate": True,
        "footprints": footprints, "nets": nets,
        "statistics": {
            "footprints": len(footprints), "nets": len(nets) - (1 if any(net["id"] == 0 for net in nets) else 0),
            "tracks": _count(text, "segment"), "vias": _count(text, "via"), "zones": _count(text, "zone"),
        },
    }


def project_info(project_path: str | Path) -> dict[str, Any]:
    path = resolve_path(project_path)
    if path.is_file():
        path = path.parent
    if not path.is_dir():
        raise KiClawError(f"Project directory not found: {path}")
    boards = sorted(path.glob("*.kicad_pcb"))
    schematics = sorted(path.glob("*.kicad_sch"))
    return {"path": str(path), "boards": [str(item) for item in boards], "schematics": [str(item) for item in schematics],
            "project_files": [str(item) for item in sorted(path.glob("*.kicad_pro"))]}


def datasheet_evidence(source: str, claims: list[str] | None = None, max_bytes: int = 5_000_000) -> dict[str, Any]:
    """Fetch a local/HTTP datasheet artifact and score only explicit text claims."""
    if not source or max_bytes <= 0 or max_bytes > 20_000_000:
        raise KiClawError("source is required and max_bytes must be between 1 and 20000000")
    if claims is not None and not isinstance(claims, list):
        raise KiClawError("claims must be a list of strings")
    requested_claims = [claim.strip() for claim in (claims or []) if isinstance(claim, str) and claim.strip()]
    source_kind = "url" if source.lower().startswith(("http://", "https://")) else "file"
    content_type = None
    if source_kind == "url":
        request = urllib.request.Request(source, headers={"User-Agent": "KiClaw/0.1 evidence-fetch"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                content_type = response.headers.get_content_type()
                payload = response.read(max_bytes + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise KiClawError(f"Could not fetch evidence source: {exc}") from exc
    else:
        path = resolve_path(source)
        if not path.is_file():
            raise KiClawError(f"Evidence source not found: {path}")
        content_type = __import__("mimetypes").guess_type(path.name)[0]
        payload = path.read_bytes()
    if len(payload) > max_bytes:
        raise KiClawError(f"Evidence source exceeds max_bytes={max_bytes}")
    digest = hashlib.sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8", errors="ignore")
    except Exception:
        text = ""
    normalized = re.sub(r"\s+", " ", text).strip()
    claim_results = [{"claim": claim, "found": claim.casefold() in normalized.casefold()} for claim in requested_claims]
    if not requested_claims:
        confidence = "medium" if payload else "low"
    elif all(item["found"] for item in claim_results):
        confidence = "high"
    elif any(item["found"] for item in claim_results):
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "ok": True,
        "source": source,
        "source_kind": source_kind,
        "content_type": content_type,
        "bytes": len(payload),
        "sha256": digest,
        "claims": claim_results,
        "confidence": confidence,
        "evidence": "Exact case-insensitive text presence in the retrieved artifact; this does not replace engineering interpretation or datasheet review.",
    }


def _balanced_sexpr_span(text: str, start: int, limit: int | None = None) -> int:
    """Return the exclusive end of a balanced S-expression starting at ``start``."""
    if start >= len(text) or text[start] != "(":
        raise KiClawError("S-expression does not start with '('")
    end_limit = len(text) if limit is None else limit
    depth, quoted, escaped = 0, False, False
    for index in range(start, end_limit):
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
                return index + 1
    raise KiClawError("Unbalanced S-expression")


def _sexpr_root_span(text: str) -> tuple[int, int]:
    start = next((index for index, char in enumerate(text) if not char.isspace()), None)
    if start is None or text[start] != "(":
        raise KiClawError("S-expression document is empty or does not start with '('")
    end = _balanced_sexpr_span(text, start)
    if text[end:].strip():
        raise KiClawError("Unexpected content after the root S-expression")
    return start, end


def _sexpr_top_level_children(text: str, root_start: int, root_end: int) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    index = root_start + 1
    while index < root_end - 1:
        if text[index].isspace():
            index += 1
            continue
        if text[index] != "(":
            index += 1
            continue
        end = _balanced_sexpr_span(text, index, root_end)
        match = re.match(r"\(\s*([^\s()]+)", text[index:end])
        if match:
            children.append({"keyword": match.group(1), "start": index, "end": end})
        index = end
    return children


def schematic_summary(schematic: str | Path) -> dict[str, Any]:
    """Return structural schematic metadata without rewriting the source file."""
    path = resolve_path(schematic, ".kicad_sch")
    if not path.is_file():
        raise KiClawError(f"Schematic not found: {path}")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KiClawError(f"Schematic is not valid UTF-8: {exc}") from exc
    root_start, root_end = _sexpr_root_span(text)
    root = text[root_start:root_end]
    root_keyword = re.match(r"\(\s*([^\s()]+)", root)
    if not root_keyword or root_keyword.group(1) != "kicad_sch":
        raise KiClawError("Schematic root must be kicad_sch")
    children = _sexpr_top_level_children(text, root_start, root_end)
    counts = Counter(child["keyword"] for child in children)
    version = re.search(r"\(version\s+([^\s()]+)\)", root)
    document_uuid = re.search(r'\(uuid\s+"([^"]+)"\)', root)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_length": len(raw),
        "encoding": "utf-8",
        "root": "kicad_sch",
        "version": version.group(1) if version else None,
        "uuid": document_uuid.group(1) if document_uuid else None,
        "top_level_counts": dict(sorted(counts.items())),
        "approximate": False,
        "write_backend": "not-yet-enabled",
    }


def schematic_roundtrip_check(schematic: str | Path) -> dict[str, Any]:
    """Verify structural validity and byte-preserving identity before schematic writes exist."""
    path = resolve_path(schematic, ".kicad_sch")
    summary = schematic_summary(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    root_start, root_end = _sexpr_root_span(text)
    reconstructed = text[:root_start] + text[root_start:root_end] + text[root_end:]
    reconstructed_bytes = reconstructed.encode("utf-8")
    source_hash = hashlib.sha256(raw).hexdigest()
    reconstructed_hash = hashlib.sha256(reconstructed_bytes).hexdigest()
    exact = raw == reconstructed_bytes and source_hash == reconstructed_hash
    return {
        "ok": exact,
        "schematic": summary,
        "round_trip": {
            "structurally_balanced": True,
            "byte_exact": exact,
            "source_sha256": source_hash,
            "reconstructed_sha256": reconstructed_hash,
            "bytes_changed": len(reconstructed_bytes) - len(raw),
        },
        "mutation_ready": False,
        "note": "This verifier proves the parser boundary preserves the original bytes; schematic mutation is intentionally not enabled until semantic round-trip fixtures are added.",
    }


def _snapshot_root(path: Path) -> Path:
    return path.parent / ".kiclaw" / "snapshots"


def snapshot_create(board: str | Path, label: str = "manual") -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    if not path.is_file():
        raise KiClawError(f"Board not found: {path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip(".-")[:32] or "manual"
    snapshot_id = f"{stamp}-{uuid.uuid4().hex[:8]}-{safe_label}"
    destination = _snapshot_root(path) / snapshot_id
    destination.mkdir(parents=True, exist_ok=False)
    saved = destination / path.name
    shutil.copy2(path, saved)
    stat = path.stat()
    metadata = {"id": snapshot_id, "board": str(path), "sha256": sha256(path), "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "created_at": datetime.now(timezone.utc).isoformat(), "label": label}
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def snapshot_list(board: str | Path) -> list[dict[str, Any]]:
    path = resolve_path(board, ".kicad_pcb")
    root = _snapshot_root(path)
    if not root.is_dir():
        return []
    items = []
    for metadata in sorted(root.glob("*/metadata.json"), reverse=True):
        data = json.loads(metadata.read_text(encoding="utf-8"))
        if data.get("board") == str(path):
            items.append(data)
    return items


def snapshot_restore(board: str | Path, snapshot_id: str, expected_sha256: str | None = None, force: bool = False) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    if not snapshot_id or Path(snapshot_id).name != snapshot_id or snapshot_id in {".", ".."}:
        raise KiClawError("Invalid snapshot id")
    source = _snapshot_root(path) / snapshot_id / path.name
    if not source.is_file():
        raise KiClawError(f"Snapshot not found for this board: {snapshot_id}")
    transaction = begin_transaction(path, "snapshot_restore", None if force else expected_sha256)
    safety_snapshot = transaction.take_snapshot("before-restore")
    transaction.commit(source.read_text(encoding="utf-8"))
    return {"ok": True, "transaction_id": transaction.transaction_id, "restored_snapshot": snapshot_id,
            "safety_snapshot": safety_snapshot["id"], "sha256": sha256(path)}


def _atomic_write(path: Path, content: str) -> None:
    mode = path.stat().st_mode if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _transaction_root(path: Path) -> Path:
    return path.parent / ".kiclaw" / "transactions"


def _session_path(path: Path) -> Path:
    return path.parent / ".kiclaw" / "backend-session.json"


def pin_backend(path: str | Path, backend: str) -> dict[str, Any]:
    """Pin a board to one backend for its project session."""
    board = resolve_path(path, ".kicad_pcb")
    session_path = _session_path(board)
    if session_path.exists():
        data = json.loads(session_path.read_text(encoding="utf-8"))
    else:
        data = {"version": 1, "boards": {}}
    boards = data.setdefault("boards", {})
    key = str(board)
    existing = boards.get(key)
    if existing and existing.get("backend") != backend:
        raise KiClawConflictError(
            f"Board session is pinned to backend {existing['backend']!r}; refusing silent switch to {backend!r}."
        )
    if not existing:
        existing = {"session_id": uuid.uuid4().hex, "backend": backend, "created_at": datetime.now(timezone.utc).isoformat()}
        boards[key] = existing
        session_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(session_path, json.dumps(data, indent=2, sort_keys=True))
    return {"board": key, **existing}


def backend_session_info(board: str | Path) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    session_path = _session_path(path)
    if not session_path.exists():
        return {"pinned": False, "board": str(path)}
    data = json.loads(session_path.read_text(encoding="utf-8"))
    session = data.get("boards", {}).get(str(path))
    return {"pinned": session is not None, "board": str(path), **(session or {})}


@dataclass
class BoardTransaction:
    """A guarded, auditable write transaction for one board file."""

    board: Path
    operation: str
    backend: str
    before_sha256: str
    before_content: str
    before_summary: dict[str, Any]
    session_id: str
    transaction_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    snapshot_id: str | None = None
    status: str = "pending"

    @property
    def manifest_path(self) -> Path:
        return _transaction_root(self.board) / f"{self.transaction_id}.json"

    def manifest(self, **extra: Any) -> dict[str, Any]:
        value = {
            "transaction_id": self.transaction_id,
            "operation": self.operation,
            "backend": self.backend,
            "session_id": self.session_id,
            "board": str(self.board),
            "status": self.status,
            "before_sha256": self.before_sha256,
            "snapshot_id": self.snapshot_id,
        }
        value.update(extra)
        return value

    def persist(self, **extra: Any) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.manifest_path, json.dumps(self.manifest(**extra), indent=2, sort_keys=True))

    def assert_unchanged(self) -> None:
        current = sha256(self.board)
        if current != self.before_sha256:
            raise KiClawConflictError(
                f"Board changed during transaction {self.transaction_id}; expected {self.before_sha256}, found {current}."
            )

    def take_snapshot(self, label: str) -> dict[str, Any]:
        self.assert_unchanged()
        snapshot = snapshot_create(self.board, label)
        self.snapshot_id = snapshot["id"]
        self.persist(snapshot=snapshot)
        return snapshot

    def commit(self, content: str, validator: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        self.assert_unchanged()
        attempted_sha256: str | None = None
        try:
            _atomic_write(self.board, content)
            attempted_sha256 = sha256(self.board)
            after = board_summary(self.board)
            if validator:
                validator(after)
        except Exception as exc:
            # Restore only when the file still contains our attempted write. If another
            # process changed it, preserve that change and surface the conflict.
            try:
                current_sha256 = sha256(self.board)
                if attempted_sha256 is not None and current_sha256 == attempted_sha256:
                    _atomic_write(self.board, self.before_content)
                elif attempted_sha256 is not None and current_sha256 != attempted_sha256:
                    self.status = "conflict"
                    self.persist(error=f"External change detected during commit: {current_sha256}")
                    raise KiClawConflictError("Board changed during post-write verification; attempted change was not rolled back.") from exc
            finally:
                if self.status != "conflict":
                    self.status = "rolled_back"
                    self.persist(error=str(exc))
            raise
        self.status = "committed"
        after_sha256 = sha256(self.board)
        self.persist(after_sha256=after_sha256, after_summary=after)
        return after


def _schematic_snapshot_root(path: Path) -> Path:
    return path.parent / ".kiclaw" / "schematic-snapshots"


@dataclass
class SchematicTransaction:
    """A guarded transaction for format-preserving schematic edits."""

    schematic: Path
    operation: str
    before_sha256: str
    before_content: str
    before_summary: dict[str, Any]
    transaction_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    snapshot_id: str | None = None
    status: str = "pending"

    @property
    def manifest_path(self) -> Path:
        return _transaction_root(self.schematic) / f"{self.transaction_id}.json"

    def manifest(self, **extra: Any) -> dict[str, Any]:
        value = {
            "transaction_id": self.transaction_id,
            "kind": "schematic",
            "operation": self.operation,
            "backend": "file",
            "schematic": str(self.schematic),
            "status": self.status,
            "before_sha256": self.before_sha256,
            "snapshot_id": self.snapshot_id,
        }
        value.update(extra)
        return value

    def persist(self, **extra: Any) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.manifest_path, json.dumps(self.manifest(**extra), indent=2, sort_keys=True))

    def assert_unchanged(self) -> None:
        current = sha256(self.schematic)
        if current != self.before_sha256:
            raise KiClawConflictError(
                f"Schematic changed during transaction {self.transaction_id}; expected {self.before_sha256}, found {current}."
            )

    def take_snapshot(self, label: str) -> dict[str, Any]:
        self.assert_unchanged()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip(".-")[:32] or "manual"
        snapshot_id = f"{stamp}-{uuid.uuid4().hex[:8]}-{safe_label}"
        destination = _schematic_snapshot_root(self.schematic) / snapshot_id
        destination.mkdir(parents=True, exist_ok=False)
        saved = destination / self.schematic.name
        shutil.copy2(self.schematic, saved)
        metadata = {"id": snapshot_id, "schematic": str(self.schematic), "sha256": self.before_sha256,
                    "size": self.schematic.stat().st_size, "created_at": datetime.now(timezone.utc).isoformat(), "label": label}
        _atomic_write(destination / "metadata.json", json.dumps(metadata, indent=2))
        self.snapshot_id = snapshot_id
        self.persist(snapshot=metadata)
        return metadata

    def commit(self, content: str, validator: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        self.assert_unchanged()
        attempted_sha256: str | None = None
        try:
            _atomic_write(self.schematic, content)
            attempted_sha256 = sha256(self.schematic)
            after = schematic_summary(self.schematic)
            if validator:
                validator(after)
        except Exception as exc:
            current_sha256 = sha256(self.schematic)
            if attempted_sha256 is not None and current_sha256 == attempted_sha256:
                _atomic_write(self.schematic, self.before_content)
            elif attempted_sha256 is not None and current_sha256 != attempted_sha256:
                self.status = "conflict"
                self.persist(error=f"External change detected during commit: {current_sha256}")
                raise KiClawConflictError("Schematic changed during post-write verification; attempted change was not rolled back.") from exc
            self.status = "rolled_back"
            self.persist(error=str(exc))
            raise
        self.status = "committed"
        self.persist(after_sha256=sha256(self.schematic), after_summary=after)
        return after


def begin_schematic_transaction(schematic: str | Path, operation: str, expected_sha256: str | None = None) -> SchematicTransaction:
    path = resolve_path(schematic, ".kicad_sch")
    if not path.is_file():
        raise KiClawError(f"Schematic not found: {path}")
    before_sha256 = sha256(path)
    if expected_sha256 and expected_sha256 != before_sha256:
        raise KiClawConflictError(f"Stale schematic hash: expected {expected_sha256}, found {before_sha256}.")
    transaction = SchematicTransaction(path, operation, before_sha256, path.read_text(encoding="utf-8"), schematic_summary(path))
    transaction.persist(before_summary=transaction.before_summary)
    return transaction


def begin_transaction(board: str | Path, operation: str, expected_sha256: str | None = None, backend: str = "file") -> BoardTransaction:
    path = resolve_path(board, ".kicad_pcb")
    if not path.is_file():
        raise KiClawError(f"Board not found: {path}")
    before_sha256 = sha256(path)
    if expected_sha256 and expected_sha256 != before_sha256:
        raise KiClawConflictError(f"Stale board hash: expected {expected_sha256}, found {before_sha256}.")
    session = pin_backend(path, backend)
    transaction = BoardTransaction(path, operation, backend, before_sha256, path.read_text(encoding="utf-8"), board_summary(path), session["session_id"])
    transaction.persist(before_summary=transaction.before_summary)
    return transaction


def _issue_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    return sum(len(payload.get(key, [])) for key in ("violations", "unconnected_items", "items") if isinstance(payload.get(key), list))


def run_check(kind: str, source: str | Path) -> dict[str, Any]:
    if kind not in {"drc", "erc"}:
        raise KiClawError(f"Unknown check kind: {kind}")
    suffix = ".kicad_pcb" if kind == "drc" else ".kicad_sch"
    path = resolve_path(source, suffix)
    if not path.is_file():
        raise KiClawError(f"Input not found: {path}")
    cli = find_kicad_cli()
    if not cli:
        return {"ok": False, "available": False, "reason": "kicad-cli was not found", "kind": kind}
    with tempfile.TemporaryDirectory(prefix="kiclaw-") as directory:
        report = Path(directory) / f"{kind}.json"
        command = [str(cli), "pcb", "drc"] if kind == "drc" else [str(cli), "sch", "erc"]
        command += ["--format", "json", "--output", str(report), str(path)]
        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=120)
        except subprocess.TimeoutExpired as exc:
            return {"ok": False, "available": True, "kind": kind, "timed_out": True,
                    "reason": "KiCad did not finish within 120 seconds", "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""}
        except OSError as exc:
            return {"ok": False, "available": False, "kind": kind, "reason": f"Could not execute kicad-cli: {exc}"}
        payload: Any = None
        if report.exists():
            raw_report = report.read_text(encoding="utf-8")
            try:
                payload = json.loads(raw_report)
            except json.JSONDecodeError:
                payload = {"raw": raw_report}
    return {"ok": completed.returncode == 0, "available": True, "kind": kind, "exit_code": completed.returncode,
            "issues": _issue_count(payload), "report": payload, "stderr": completed.stderr.strip()}


def run_export(kind: str, board: str | Path, output: str | Path) -> dict[str, Any]:
    if kind not in {"gerbers", "drill", "svg", "ipc2581"}:
        raise KiClawError(f"Unknown export kind: {kind}")
    path, destination = resolve_path(board, ".kicad_pcb"), resolve_path(output)
    if not path.is_file():
        raise KiClawError(f"Board not found: {path}")
    cli = find_kicad_cli()
    if not cli:
        return {"ok": False, "available": False, "reason": "kicad-cli was not found"}
    if kind in {"svg", "ipc2581"}:
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination.mkdir(parents=True, exist_ok=True)
    subcommand = {
        "gerbers": ["pcb", "export", "gerbers"],
        "drill": ["pcb", "export", "drill"],
        "svg": ["pcb", "export", "svg", "--mode-single", "--layers", "F.Cu,B.Cu,Edge.Cuts"],
        "ipc2581": ["pcb", "export", "ipc2581"],
    }[kind]
    try:
        completed = subprocess.run([str(cli), *subcommand, "--output", str(destination), str(path)], text=True, capture_output=True, check=False, timeout=180)
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "available": True, "kind": kind, "output": str(destination), "timed_out": True,
                "reason": "KiCad did not finish within 180 seconds", "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""}
    except OSError as exc:
        return {"ok": False, "available": False, "kind": kind, "output": str(destination), "reason": f"Could not execute kicad-cli: {exc}"}
    outputs = [str(item) for item in (destination.parent.glob(destination.name + "*") if kind in {"svg", "ipc2581"} else destination.iterdir())] if destination.exists() else []
    return {"ok": completed.returncode == 0, "kind": kind, "output": str(destination), "files": sorted(outputs), "stderr": completed.stderr.strip()}


def _finding(category: str, severity: str, message: str, evidence: str, confidence: str, details: Any = None) -> dict[str, Any]:
    value = {"category": category, "severity": severity, "message": message, "evidence": evidence, "confidence": confidence}
    if details is not None:
        value["details"] = details
    return value


def _deterministic_board_findings(
    board: str | Path,
    minimum_trace_width: float = 0.15,
    require_fiducials: bool = False,
    require_testpoints: bool = False,
) -> list[dict[str, Any]]:
    """Run conservative DFM checks that do not depend on a KiCad GUI session."""
    if not math.isfinite(minimum_trace_width) or minimum_trace_width <= 0:
        raise KiClawError("minimum_trace_width must be a positive finite number")
    path = resolve_path(board, ".kicad_pcb")
    text = path.read_text(encoding="utf-8")
    summary = board_summary(path)
    evidence = "KiClaw deterministic KiCad S-expression analysis"
    findings: list[dict[str, Any]] = []
    graphic_forms = []
    for kind in ("gr_line", "gr_arc", "gr_circle", "gr_rect", "gr_poly", "gr_curve"):
        graphic_forms.extend(_top_level_forms(text, kind))
    edge_forms = [form for form in graphic_forms if re.search(r'\(layer\s+"Edge\.Cuts"\)', form)]
    if not edge_forms:
        findings.append(_finding("manufacturing", "error", "Board has no detectable Edge.Cuts outline.", evidence, "high"))
    edge_line_forms = [form for form in _top_level_forms(text, "gr_line") if re.search(r'\(layer\s+"Edge\.Cuts"\)', form)]
    endpoints: Counter[tuple[float, float]] = Counter()
    for form in edge_line_forms:
        start = re.search(r"\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        end = re.search(r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        if start and end:
            a = (round(float(start.group(1)), 6), round(float(start.group(2)), 6))
            b = (round(float(end.group(1)), 6), round(float(end.group(2)), 6))
            endpoints[a] += 1
            endpoints[b] += 1
    if edge_line_forms and endpoints:
        open_points = [point for point, degree in endpoints.items() if degree != 2]
        if open_points:
            findings.append(_finding("manufacturing", "error", "Edge.Cuts linework is not a closed outline.", evidence, "high",
                                     {"open_points": [list(point) for point in open_points]}))
    elif edge_forms and not edge_line_forms:
        findings.append(_finding("manufacturing", "warning", "Edge.Cuts exists, but closure could not be proven from line segments.", evidence, "medium"))
    references = [item["reference"] for item in summary["footprints"]]
    missing_references = [index for index, reference in enumerate(references) if not reference]
    if missing_references:
        findings.append(_finding("structure", "error", "One or more footprints have no reference designator.", evidence, "high",
                                 {"footprint_indexes": missing_references}))
    seen: set[str] = set()
    duplicates: list[str] = []
    for reference in references:
        if reference and reference in seen and reference not in duplicates:
            duplicates.append(reference)
        if reference:
            seen.add(reference)
    if duplicates:
        findings.append(_finding("structure", "error", "Duplicate footprint reference designators detected.", evidence, "high",
                                 {"references": duplicates}))
    if summary["statistics"]["footprints"] == 0:
        findings.append(_finding("structure", "warning", "Board contains no footprints.", evidence, "high"))
    if summary["statistics"]["nets"] == 0:
        findings.append(_finding("connectivity", "warning", "Board contains no named electrical nets.", evidence, "high"))
    missing_values = [index for index, item in enumerate(summary["footprints"]) if not item.get("value")]
    if missing_values:
        findings.append(_finding("assembly", "warning", "One or more footprints have no value field.", evidence, "high",
                                 {"footprint_indexes": missing_values}))
    invalid_widths = []
    undersized_widths = []
    for form in _top_level_forms(text, "segment"):
        width = re.search(r"\(width\s+(-?[\d.]+)\)", form)
        if width:
            value = float(width.group(1))
            if value <= 0:
                invalid_widths.append(width.group(1))
            elif value < minimum_trace_width:
                undersized_widths.append(width.group(1))
    if invalid_widths:
        findings.append(_finding("dfm", "error", "One or more copper segments have a non-positive width.", evidence, "high",
                                 {"widths": invalid_widths}))
    if undersized_widths:
        findings.append(_finding("dfm", "error", "One or more copper segments are below the configured minimum width.", evidence, "high",
                                 {"minimum_trace_width": minimum_trace_width, "widths": undersized_widths}))
    invalid_vias = []
    for form in _top_level_forms(text, "via"):
        size = re.search(r"\(size\s+(-?[\d.]+)\)", form)
        drill = re.search(r"\(drill\s+(-?[\d.]+)\)", form)
        if (size and float(size.group(1)) <= 0) or (drill and float(drill.group(1)) <= 0):
            invalid_vias.append({"size": size.group(1) if size else None, "drill": drill.group(1) if drill else None})
    if invalid_vias:
        findings.append(_finding("dfm", "error", "One or more vias have invalid size or drill geometry.", evidence, "high",
                                 {"vias": invalid_vias}))
    if require_fiducials:
        has_fiducial = any("fiducial" in str(item.get("value", "")).lower() or str(item.get("reference", "")).upper().startswith("FID")
                           for item in summary["footprints"])
        if not has_fiducial:
            findings.append(_finding("assembly", "warning", "No fiducial footprint was detected.", evidence, "medium"))
    if require_testpoints:
        has_testpoint = any(str(item.get("reference", "")).upper().startswith("TP") or "testpoint" in str(item.get("value", "")).lower()
                            for item in summary["footprints"])
        if not has_testpoint:
            findings.append(_finding("assembly", "warning", "No test-point footprint was detected.", evidence, "medium"))
    return findings


def _finding_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity", "unknown"))
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def run_dfm(
    board: str | Path,
    minimum_trace_width: float = 0.15,
    require_fiducials: bool = False,
    require_testpoints: bool = False,
) -> dict[str, Any]:
    """Run deterministic, profile-controlled design-for-manufacture checks."""
    summary = board_summary(board)
    findings = _deterministic_board_findings(board, minimum_trace_width, require_fiducials, require_testpoints)
    counts = _finding_counts(findings)
    blocking = sum(counts.get(severity, 0) for severity in ("error", "critical", "unknown"))
    return {
        "ok": blocking == 0,
        "board": summary,
        "profile": {"minimum_trace_width": minimum_trace_width, "require_fiducials": require_fiducials, "require_testpoints": require_testpoints},
        "findings": findings,
        "finding_counts": counts,
        "confidence": "high" if all(item.get("confidence") == "high" for item in findings) else "medium",
        "evidence": "KiClaw deterministic KiCad S-expression analysis",
    }


def run_emc(board: str | Path, profile: str = "conservative") -> dict[str, Any]:
    """Run conservative, evidence-labelled EMC pre-compliance heuristics."""
    if profile not in {"conservative"}:
        raise KiClawError("Only the conservative EMC profile is currently supported")
    path = resolve_path(board, ".kicad_pcb")
    text = path.read_text(encoding="utf-8")
    summary = board_summary(path)
    evidence = "KiClaw conservative EMC heuristic over KiCad board S-expressions"
    findings: list[dict[str, Any]] = []
    net_names = {str(item.get("name", "")).upper() for item in summary["nets"] if item.get("name")}
    ground_names = sorted(name for name in net_names if name in {"GND", "AGND", "DGND", "PGND", "GROUND"} or name.endswith("_GND"))
    if not ground_names:
        findings.append(_finding("emc", "warning", "No conventional ground net was detected; return-path review is unverified.", evidence, "medium"))
    else:
        ground_ids = [str(item.get("id")) for item in summary["nets"] if str(item.get("name", "")).upper() in ground_names]
        has_ground_zone = any(re.search(r"\(zone\b", form) and any(re.search(rf"\(net\s+{re.escape(net_id)}\)", form) for net_id in ground_ids)
                              for form in _top_level_forms(text, "zone"))
        if not has_ground_zone:
            findings.append(_finding("emc", "warning", "Ground net exists but no ground copper zone tied to it was detected.", evidence, "medium",
                                     {"ground_nets": ground_names}))
    power_names = sorted(name for name in net_names if name in {"VCC", "VDD", "VBUS", "+5V", "+3V3", "+3V3A", "VIN"} or name.startswith("VDD_"))
    values = [str(item.get("value", "")) for item in summary["footprints"]]
    references = [str(item.get("reference", "")) for item in summary["footprints"]]
    capacitor_present = any(reference.upper().startswith("C") or "capac" in value.lower() for reference, value in zip(references, values))
    if power_names and not capacitor_present:
        findings.append(_finding("emc", "warning", "Power nets were detected but no capacitor-like footprint was identified for decoupling review.", evidence, "low",
                                 {"power_nets": power_names}))
    connector_present = any(reference.upper().startswith(("J", "P")) or any(token in value.lower() for token in ("connector", "usb", "terminal"))
                            for reference, value in zip(references, values))
    protection_present = any(any(token in value.lower() for token in ("tvs", "esd", "pesd", "stp")) for value in values)
    if connector_present and not protection_present:
        findings.append(_finding("emc", "warning", "Connector-like footprints were detected without an obvious TVS/ESD protection footprint.", evidence, "low"))
    counts = _finding_counts(findings)
    return {"ok": not any(item["severity"] in {"error", "critical", "unknown"} for item in findings), "board": summary,
            "profile": profile, "findings": findings, "finding_counts": counts,
            "confidence": "medium", "evidence": evidence,
            "disclaimer": "Heuristics are pre-compliance indicators only; they do not replace EMC simulation, lab testing, or engineering sign-off."}


def run_si(board: str | Path, max_segment_length: float = 10.0) -> dict[str, Any]:
    """Run conservative signal-integrity indicators from net names and track geometry."""
    if not math.isfinite(max_segment_length) or max_segment_length <= 0:
        raise KiClawError("max_segment_length must be a positive finite number")
    path = resolve_path(board, ".kicad_pcb")
    text = path.read_text(encoding="utf-8")
    summary = board_summary(path)
    evidence = "KiClaw conservative SI/PI heuristic over KiCad board S-expressions"
    findings: list[dict[str, Any]] = []
    high_speed = sorted(name for name in (str(item.get("name", "")) for item in summary["nets"]) if re.search(r"(?i)(CLK|USB|SPI|MISO|MOSI|LVDS|HDMI|PCIE|DDR|SERDES|D[+\-])", name))
    if high_speed:
        findings.append(_finding("si", "warning", "High-speed net names were detected; controlled impedance and length matching require stackup-aware analysis.", evidence, "medium",
                                 {"nets": high_speed}))
        differential = {name[:-2] for name in high_speed if name.endswith(("_P", "+"))} & {name[:-2] for name in high_speed if name.endswith(("_N", "-"))}
        if not differential:
            findings.append(_finding("si", "warning", "No complementary differential net pair was confidently identified among high-speed nets.", evidence, "low"))
    net_by_id = {int(item["id"]): str(item.get("name", "")) for item in summary["nets"] if str(item.get("id", "")).isdigit()}
    long_segments: list[dict[str, Any]] = []
    for form in _top_level_forms(text, "segment"):
        net_match = re.search(r"\(net\s+(\d+)\)", form)
        start = re.search(r"\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        end = re.search(r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)", form)
        if net_match and start and end and net_by_id.get(int(net_match.group(1))) in high_speed:
            length = math.hypot(float(end.group(1)) - float(start.group(1)), float(end.group(2)) - float(start.group(2)))
            if length > max_segment_length:
                long_segments.append({"net": net_by_id[int(net_match.group(1))], "length_mm": round(length, 6)})
    if long_segments:
        findings.append(_finding("si", "warning", "High-speed segments exceed the configured single-segment review length.", evidence, "low",
                                 {"maximum_mm": max_segment_length, "segments": long_segments}))
    counts = _finding_counts(findings)
    return {"ok": not any(item["severity"] in {"error", "critical", "unknown"} for item in findings), "board": summary,
            "profile": {"max_segment_length": max_segment_length}, "findings": findings, "finding_counts": counts,
            "confidence": "medium", "evidence": evidence,
            "disclaimer": "Indicators do not calculate impedance, crosstalk, eye diagrams, timing margins, or power-integrity ripple."}


def run_thermal(board: str | Path, profile: str = "conservative") -> dict[str, Any]:
    """Run conservative thermal-management indicators from board structure."""
    if profile not in {"conservative"}:
        raise KiClawError("Only the conservative thermal profile is currently supported")
    path = resolve_path(board, ".kicad_pcb")
    text = path.read_text(encoding="utf-8")
    summary = board_summary(path)
    evidence = "KiClaw conservative thermal heuristic over KiCad board S-expressions"
    findings: list[dict[str, Any]] = []
    power_names = sorted(name for name in (str(item.get("name", "")).upper() for item in summary["nets"]) if name in {"VBUS", "+5V", "+12V", "VIN", "VDD", "VCC"} or name.startswith(("VDD_", "VCC_")))
    values = [str(item.get("value", "")) for item in summary["footprints"]]
    hot_parts = [value for value in values if re.search(r"(?i)(regulator|ldo|buck|boost|mosfet|power|driver|amplifier|heatsink|dc[- ]?dc)", value)]
    zones = _top_level_forms(text, "zone")
    if hot_parts and not zones:
        findings.append(_finding("thermal", "warning", "Power-dissipating component values were detected without any copper zone for thermal spreading.", evidence, "low",
                                 {"components": hot_parts}))
    if power_names and not zones:
        findings.append(_finding("thermal", "warning", "Power rails were detected but no copper zones were found; thermal spreading is unverified.", evidence, "medium",
                                 {"power_nets": power_names}))
    if hot_parts and not any(re.search(r"(?i)(heatsink|thermal|powerpad|qfn|qfp|soic)", value) for value in values):
        findings.append(_finding("thermal", "warning", "Potentially hot components were detected without an obvious thermal-package/heatsink indicator.", evidence, "low"))
    counts = _finding_counts(findings)
    return {"ok": not any(item["severity"] in {"error", "critical", "unknown"} for item in findings), "board": summary,
            "profile": profile, "findings": findings, "finding_counts": counts,
            "confidence": "low" if findings else "medium", "evidence": evidence,
            "disclaimer": "Indicators do not compute junction temperature, thermal resistance, airflow, or derating against a datasheet."}


def run_analysis(
    board: str | Path,
    packs: list[str] | tuple[str, ...] | None = None,
    *,
    max_decoupling_distance_mm: float = 5.0,
    max_protection_distance_mm: float = 15.0,
    strict_connectivity: bool = False,
) -> dict[str, Any]:
    """Run deterministic deep analysis packs (power, decoupling, protection, …)."""
    # Lazy import keeps core loadable without circular imports at module import time.
    from .analysis import run_analysis as _run_analysis

    return _run_analysis(
        board,
        packs=packs,
        max_decoupling_distance_mm=max_decoupling_distance_mm,
        max_protection_distance_mm=max_protection_distance_mm,
        strict_connectivity=strict_connectivity,
    )


def run_deep_analysis(board: str | Path, **kwargs: Any) -> dict[str, Any]:
    """Alias for :func:`run_analysis`."""
    return run_analysis(board, **kwargs)


def review_board(board: str | Path, include_analysis: bool = True) -> dict[str, Any]:
    """Produce an evidence-labelled native plus deterministic manufacturing review."""
    summary = board_summary(board)
    drc = run_check("drc", board)
    dfm = run_dfm(board)
    emc = run_emc(board)
    si = run_si(board)
    thermal = run_thermal(board)
    analysis = run_analysis(board) if include_analysis else None
    findings = list(dfm["findings"]) + list(emc["findings"]) + list(si["findings"]) + list(thermal["findings"])
    if analysis is not None:
        findings.extend(analysis["findings"])
    report = drc.get("report")
    if isinstance(report, dict):
        for violation in report.get("violations", []):
            if isinstance(violation, dict):
                findings.append(_finding("drc", violation.get("severity", "error"),
                                         violation.get("description", "KiCad reported a design-rule violation"),
                                         "KiCad native DRC JSON report", "high", violation))
        for item in report.get("unconnected_items", []):
            findings.append(_finding("connectivity", "error", "Unconnected item reported by KiCad",
                                     "KiCad native DRC JSON report", "high", item))
    elif not drc.get("available") or not drc.get("report"):
        findings.append(_finding("verification", "unknown",
                                 "Native DRC could not provide a report; design cleanliness is unverified.",
                                 drc.get("reason", "KiCad DRC returned no report"), "high"))
    counts = _finding_counts(findings)
    blocking = sum(counts.get(severity, 0) for severity in ("error", "critical", "unknown"))
    checks: dict[str, Any] = {"drc": drc, "dfm": dfm, "emc": emc, "si": si, "thermal": thermal}
    if analysis is not None:
        checks["analysis"] = analysis
    return {
        "ok": drc.get("ok") is True and blocking == 0,
        "board": summary,
        "checks": checks,
        "findings": findings,
        "finding_counts": counts,
        "confidence": "high" if isinstance(report, dict) else "medium",
        "disclaimer": "This is a first-pass review; it does not replace engineering sign-off, datasheet checks, or fabrication approval.",
    }


def review_project(project_path: str | Path) -> dict[str, Any]:
    """Review every board and schematic in a project with one machine-readable result."""
    info = project_info(project_path)
    board_reviews = [review_board(board) for board in info["boards"]]
    erc_checks = [run_check("erc", schematic) for schematic in info["schematics"]]
    findings: list[dict[str, Any]] = []
    for review in board_reviews:
        for finding in review["findings"]:
            findings.append({**finding, "source": review["board"]["path"]})
    for schematic, check in zip(info["schematics"], erc_checks):
        report = check.get("report")
        if isinstance(report, dict):
            for violation in report.get("violations", []):
                if isinstance(violation, dict):
                    findings.append(_finding("erc", violation.get("severity", "error"),
                                             violation.get("description", "KiCad reported an electrical-rule violation"),
                                             "KiCad native ERC JSON report", "high", violation) | {"source": schematic})
        elif not check.get("available") or not check.get("report"):
            findings.append(_finding("verification", "unknown", "Native ERC could not provide a report; schematic cleanliness is unverified.",
                                     check.get("reason", "KiCad ERC returned no report"), "high") | {"source": schematic})
    if not info["boards"] and not info["schematics"]:
        findings.append(_finding("project", "warning", "Project contains no KiCad board or schematic files.",
                                 "Project directory scan", "high"))
    counts = _finding_counts(findings)
    blocking = sum(counts.get(severity, 0) for severity in ("error", "critical", "unknown"))
    return {
        "ok": blocking == 0,
        "project": info,
        "boards": board_reviews,
        "schematics": [{"path": path, "erc": check} for path, check in zip(info["schematics"], erc_checks)],
        "findings": findings,
        "finding_counts": counts,
        "confidence": "high" if not findings or all(item.get("confidence") == "high" for item in findings) else "medium",
        "disclaimer": "This is a first-pass project review; it does not replace engineering sign-off, datasheet checks, or fabrication approval.",
    }


def _schematic_insert_before_sheet_instances(text: str) -> int:
    root_start, root_end = _sexpr_root_span(text)
    children = _sexpr_top_level_children(text, root_start, root_end)
    sheet = next((child for child in children if child["keyword"] == "sheet_instances"), None)
    return int(sheet["start"] if sheet else root_end - 1)


def add_wire(
    schematic: str | Path,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Insert one schematic wire while preserving every existing source byte."""
    coordinates = (start_x, start_y, end_x, end_y)
    if not all(math.isfinite(value) for value in coordinates):
        raise KiClawError("wire coordinates must be finite numbers")
    transaction = begin_schematic_transaction(schematic, "add_wire", expected_sha256)
    before = transaction.before_summary
    snapshot = transaction.take_snapshot("before-add-wire")
    text = transaction.before_content
    insertion = _schematic_insert_before_sheet_instances(text)
    x1, y1, x2, y2 = (format(value, ".12g") for value in coordinates)
    wire = (
        f'\t(wire\n'
        f'\t\t(pts\n'
        f'\t\t\t(xy {x1} {y1}) (xy {x2} {y2})\n'
        f'\t\t)\n'
        f'\t\t(stroke\n'
        f'\t\t\t(width 0)\n'
        f'\t\t\t(type solid)\n'
        f'\t\t)\n'
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t)\n'
    )
    content = text[:insertion] + wire + text[insertion:]

    def verify(after: dict[str, Any]) -> None:
        before_wires = before["top_level_counts"].get("wire", 0)
        after_wires = after["top_level_counts"].get("wire", 0)
        if after_wires != before_wires + 1:
            raise KiClawError(f"Post-write verification failed: expected wire count {before_wires + 1}, found {after_wires}")
        roundtrip = schematic_roundtrip_check(transaction.schematic)
        if not roundtrip["ok"]:
            raise KiClawError("Post-write schematic round-trip verification failed")

    after = transaction.commit(content, verify)
    erc = run_check("erc", transaction.schematic)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "schematic": str(transaction.schematic),
        "wire": {"start": [start_x, start_y], "end": [end_x, end_y]},
        "diff": {
            "sha256": {"before": before["sha256"], "after": after["sha256"]},
            "top_level_counts": {
                "wire": after["top_level_counts"].get("wire", 0) - before["top_level_counts"].get("wire", 0),
            },
        },
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": erc},
    }


def _schematic_symbol_forms(text: str) -> list[str]:
    root_start, root_end = _sexpr_root_span(text)
    return [text[child["start"]:child["end"]] for child in _sexpr_top_level_children(text, root_start, root_end) if child["keyword"] == "symbol"]


def add_component(
    schematic: str | Path,
    lib_id: str,
    reference: str,
    x: float,
    y: float,
    value: str | None = None,
    rotation: float = 0.0,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Clone an existing schematic symbol instance with new UUIDs and placement.

    This deliberately requires an existing instance of ``lib_id`` in the same
    schematic. It avoids inventing library serialization until custom-symbol
    fixtures exist, while still providing a useful, auditable component edit.
    """
    if not lib_id or not reference or not all(math.isfinite(number) for number in (x, y, rotation)):
        raise KiClawError("lib_id/reference are required and placement values must be finite numbers")
    transaction = begin_schematic_transaction(schematic, "add_component", expected_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    symbols = _schematic_symbol_forms(text)
    if any(re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', form) for form in symbols):
        raise KiClawConflictError(f"Schematic reference already exists: {reference}")
    template = next((form for form in symbols if re.search(r'\(lib_id\s+"' + re.escape(lib_id) + r'"\)', form)), None)
    if template is None:
        raise KiClawError(f"No existing symbol instance for lib_id {lib_id!r}; custom library insertion is not enabled yet")
    snapshot = transaction.take_snapshot("before-add-component")
    at = re.search(r"\(at\s+-?[\d.]+\s+-?[\d.]+(?:\s+-?[\d.]+)?\)", template)
    if at is None:
        raise KiClawError("Existing symbol instance has no editable placement")
    replacement = f"(at {format(x, '.12g')} {format(y, '.12g')} {format(rotation, '.12g')})"
    clone = template.replace(at.group(0), replacement, 1)
    clone = re.sub(r'(\(property\s+"Reference"\s+")[^"]+(")', rf'\g<1>{reference}\g<2>', clone, count=1)
    if value is not None:
        clone = re.sub(r'(\(property\s+"Value"\s+")[^"]+(")', rf'\g<1>{value}\g<2>', clone, count=1)
    clone = re.sub(r'\(reference\s+"[^"]*"\)', f'(reference "{reference}")', clone, count=1)
    uuid_map: dict[str, str] = {}
    def replace_uuid(match: re.Match[str]) -> str:
        old = match.group(1)
        uuid_map.setdefault(old, str(uuid.uuid4()))
        return f'(uuid "{uuid_map[old]}")'
    clone = re.sub(r'\(uuid\s+"([^"]+)"\)', replace_uuid, clone)
    insertion = _schematic_insert_before_sheet_instances(text)
    content = text[:insertion] + clone + "\n" + text[insertion:]

    def verify(after: dict[str, Any]) -> None:
        before_symbols = before["top_level_counts"].get("symbol", 0)
        after_symbols = after["top_level_counts"].get("symbol", 0)
        if after_symbols != before_symbols + 1:
            raise KiClawError(f"Post-write verification failed: expected symbol count {before_symbols + 1}, found {after_symbols}")
        if sum(1 for form in _schematic_symbol_forms(transaction.schematic.read_text(encoding="utf-8"))
               if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', form)) != 1:
            raise KiClawError(f"Post-write verification failed for reference {reference}")
        if not schematic_roundtrip_check(transaction.schematic)["ok"]:
            raise KiClawError("Post-write schematic round-trip verification failed")

    after = transaction.commit(content, verify)
    erc = run_check("erc", transaction.schematic)
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "schematic": str(transaction.schematic),
        "component": {"lib_id": lib_id, "reference": reference, "value": value, "at": [x, y], "rotation": rotation},
        "diff": {"sha256": {"before": before["sha256"], "after": after["sha256"]},
                 "top_level_counts": {"symbol": after["top_level_counts"].get("symbol", 0) - before["top_level_counts"].get("symbol", 0)}},
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": erc},
        "limitation": "Component insertion clones an existing lib_id instance; custom symbol/library generation is not enabled yet.",
    }


def _install_project_symbol_library(project: Path, nickname: str, symbol_definition: str) -> dict[str, Any]:
    """Install a generated project-local symbol library and table entry."""
    if not nickname or any(char.isspace() for char in nickname) or '"' in nickname:
        raise KiClawError("Symbol library nickname must be a non-empty token")
    library_path = project / f"{nickname}.kicad_sym"
    table_path = project / "sym-lib-table"
    previous_library = library_path.read_text(encoding="utf-8") if library_path.exists() else None
    previous_table = table_path.read_text(encoding="utf-8") if table_path.exists() else None
    symbol_name = re.match(r'\(symbol\s+"([^"]+)"', symbol_definition)
    if symbol_name is None:
        raise KiClawError("Generated symbol definition has no name")
    short_name = symbol_name.group(1).rsplit(":", 1)[-1]
    definition = symbol_definition.replace(f'"{symbol_name.group(1)}"', f'"{short_name}"', 1)
    library = (
        '(kicad_symbol_lib\n'
        '\t(version 20251024)\n'
        '\t(generator "kiclaw")\n'
        '\t(generator_version "0.1")\n\t'
        + definition.replace("\n", "\n\t") + '\n)\n'
    )
    _atomic_write(library_path, library)
    table = previous_table or "(sym_lib_table\n\t(version 7)\n)\n"
    if f'(lib (name "{nickname}")' not in table:
        insertion = table.rfind(")")
        if insertion < 0:
            raise KiClawError("Existing sym-lib-table is not valid S-expression")
        entry = f'\t(lib (name "{nickname}") (type "KiCad") (uri "${{KIPRJMOD}}/{nickname}.kicad_sym") (options "") (descr "Generated by KiClaw"))\n'
        table = table[:insertion] + entry + table[insertion:]
        _atomic_write(table_path, table)
    return {"library": str(library_path), "table": str(table_path), "previous_library": previous_library, "previous_table": previous_table}


def add_custom_component(
    schematic: str | Path,
    source_lib_id: str,
    new_lib_id: str,
    reference: str,
    x: float,
    y: float,
    value: str | None = None,
    rotation: float = 0.0,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Clone a known-good library definition and instance under a new library ID."""
    if not source_lib_id or not new_lib_id or '"' in new_lib_id or any(char.isspace() for char in new_lib_id):
        raise KiClawError("source_lib_id and new_lib_id are required and new_lib_id cannot contain whitespace or quotes")
    if not all(math.isfinite(number) for number in (x, y, rotation)):
        raise KiClawError("component placement and rotation must be finite numbers")
    transaction = begin_schematic_transaction(schematic, "add_custom_component", expected_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    definitions = [form for form in _top_level_forms(text, "symbol") if re.match(r'\(symbol\s+"', form)]
    definition = next((form for form in definitions if re.match(r'\(symbol\s+"' + re.escape(source_lib_id) + r'"', form)), None)
    if definition is None:
        raise KiClawError(f"No library definition for {source_lib_id!r} exists in this schematic")
    if any(re.match(r'\(symbol\s+"' + re.escape(new_lib_id) + r'"', form) for form in definitions):
        raise KiClawConflictError(f"Library ID already exists: {new_lib_id}")
    symbols = _schematic_symbol_forms(text)
    if any(re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', form) for form in symbols):
        raise KiClawConflictError(f"Schematic reference already exists: {reference}")
    instance = next((form for form in symbols if re.search(r'\(lib_id\s+"' + re.escape(source_lib_id) + r'"\)', form)), None)
    if instance is None:
        raise KiClawError(f"No existing symbol instance for {source_lib_id!r} is available as a safe instance template")
    snapshot = transaction.take_snapshot("before-add-custom-component")
    source_name = source_lib_id.rsplit(":", 1)[-1]
    new_name = new_lib_id.rsplit(":", 1)[-1]
    # KiCad treats the nested graphic/pin symbol names as part of the
    # symbol's identity.  Renaming only the outer symbol produces a file that
    # our structural parser accepts but KiCad itself cannot load.
    custom_definition = definition.replace(source_lib_id, new_lib_id)
    custom_definition = custom_definition.replace(source_name, new_name)
    custom_definition = re.sub(r'^\(symbol\s+"[^"]+"', f'(symbol "{new_lib_id}"', custom_definition, count=1)
    definition_uuid_map: dict[str, str] = {}
    def replace_definition_uuid(match: re.Match[str]) -> str:
        old = match.group(1)
        definition_uuid_map.setdefault(old, str(uuid.uuid4()))
        return f'(uuid "{definition_uuid_map[old]}")'
    custom_definition = re.sub(r'\(uuid\s+"([^"]+)"\)', replace_definition_uuid, custom_definition)
    at = re.search(r"\(at\s+-?[\d.]+\s+-?[\d.]+(?:\s+-?[\d.]+)?\)", instance)
    if at is None:
        raise KiClawError("Existing symbol instance has no editable placement")
    custom_instance = instance.replace(at.group(0), f"(at {format(x, '.12g')} {format(y, '.12g')} {format(rotation, '.12g')})", 1)
    custom_instance = re.sub(r'(\(lib_id\s+")[^"]+(")', rf'\g<1>{new_lib_id}\g<2>', custom_instance, count=1)
    custom_instance = re.sub(r'(\(property\s+"Reference"\s+")[^"]+(")', rf'\g<1>{reference}\g<2>', custom_instance, count=1)
    if value is not None:
        custom_instance = re.sub(r'(\(property\s+"Value"\s+")[^"]+(")', rf'\g<1>{value}\g<2>', custom_instance, count=1)
    custom_instance = re.sub(r'\(reference\s+"[^"]*"\)', f'(reference "{reference}")', custom_instance, count=1)
    instance_uuid_map: dict[str, str] = {}
    def replace_instance_uuid(match: re.Match[str]) -> str:
        old = match.group(1)
        instance_uuid_map.setdefault(old, str(uuid.uuid4()))
        return f'(uuid "{instance_uuid_map[old]}")'
    custom_instance = re.sub(r'\(uuid\s+"([^"]+)"\)', replace_instance_uuid, custom_instance)
    root_start, root_end = _sexpr_root_span(text)
    children = _sexpr_top_level_children(text, root_start, root_end)
    lib_child = next((child for child in children if child["keyword"] == "lib_symbols"), None)
    if lib_child is None:
        raise KiClawError("Schematic has no lib_symbols section")
    lib_insertion = int(lib_child["end"]) - 1
    content = text[:lib_insertion] + "\n\t\t" + custom_definition + text[lib_insertion:]
    instance_insertion = _schematic_insert_before_sheet_instances(content)
    content = content[:instance_insertion] + "\t" + custom_instance + "\n" + content[instance_insertion:]

    def verify(after: dict[str, Any]) -> None:
        if after["top_level_counts"].get("symbol", 0) != before["top_level_counts"].get("symbol", 0) + 1:
            raise KiClawError("Post-write verification failed: custom component count did not increase by one")
        changed = transaction.schematic.read_text(encoding="utf-8")
        if not re.search(r'\(symbol\s+"' + re.escape(new_lib_id) + r'"', changed):
            raise KiClawError("Post-write verification failed: new library definition is missing")
        if not schematic_roundtrip_check(transaction.schematic)["ok"]:
            raise KiClawError("Post-write schematic round-trip verification failed")

    after = transaction.commit(content, verify)
    nickname = new_lib_id.split(":", 1)[0] if ":" in new_lib_id else "KiClaw"
    try:
        library_state = _install_project_symbol_library(transaction.schematic.parent, nickname, custom_definition)
    except Exception:
        _atomic_write(transaction.schematic, transaction.before_content)
        transaction.status = "rolled_back"
        transaction.persist(error="Could not install generated project symbol library")
        raise
    erc = run_check("erc", transaction.schematic)
    if erc.get("exit_code") == 3 or "Failed to load schematic" in erc.get("stderr", ""):
        _atomic_write(transaction.schematic, transaction.before_content)
        library_path = Path(library_state["library"])
        table_path = Path(library_state["table"])
        if library_state["previous_library"] is None:
            library_path.unlink(missing_ok=True)
        else:
            _atomic_write(library_path, library_state["previous_library"])
        if library_state["previous_table"] is None:
            table_path.unlink(missing_ok=True)
        else:
            _atomic_write(table_path, library_state["previous_table"])
        transaction.status = "rolled_back"
        transaction.persist(error="KiCad could not load generated symbol library")
        raise KiClawError("KiCad could not load the generated symbol/library; schematic and library files were rolled back")
    return {
        "ok": True,
        "transaction_id": transaction.transaction_id,
        "snapshot_id": snapshot["id"],
        "schematic": str(transaction.schematic),
        "component": {"source_lib_id": source_lib_id, "new_lib_id": new_lib_id, "reference": reference, "value": value, "at": [x, y], "rotation": rotation},
        "diff": {"sha256": {"before": before["sha256"], "after": after["sha256"]},
                 "top_level_counts": {"symbol": after["top_level_counts"].get("symbol", 0) - before["top_level_counts"].get("symbol", 0)}},
        "verification": {"round_trip": schematic_roundtrip_check(transaction.schematic), "erc": erc},
        "library": {"nickname": nickname, "path": library_state["library"], "table": library_state["table"]},
        "limitation": "Generation clones a known-good definition; arbitrary hand-authored geometry is not yet enabled.",
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {"sha256": {"before": before["sha256"], "after": after["sha256"]},
            "statistics": {key: after["statistics"][key] - before["statistics"][key] for key in before["statistics"]}}


def add_track(board: str | Path, net_name: str, start_x: float, start_y: float, end_x: float, end_y: float, width: float = 0.25, layer: str = "F.Cu", expected_sha256: str | None = None) -> dict[str, Any]:
    path = resolve_path(board, ".kicad_pcb")
    before = board_summary(path)
    matching = [net for net in before["nets"] if net["name"] == net_name]
    if not matching or matching[0]["id"] == 0:
        raise KiClawError(f"A non-empty net named {net_name!r} was not found")
    if not all(math.isfinite(value) for value in (start_x, start_y, end_x, end_y, width)) or width <= 0 or layer not in {"F.Cu", "B.Cu"}:
        raise KiClawError("coordinates must be finite, width must be positive, and layer must be F.Cu or B.Cu")
    transaction = begin_transaction(path, "add_track", expected_sha256 or before["sha256"])
    before = transaction.before_summary
    snapshot = transaction.take_snapshot("before-add-track")
    segment = f'\n\t(segment (start {start_x} {start_y}) (end {end_x} {end_y}) (width {width}) (layer "{layer}") (net {matching[0]["id"]}))\n'
    text = transaction.before_content
    final = text.rfind(")")
    if final < 0:
        raise KiClawError("Board is not a valid S-expression")
    content = text[:final] + segment + text[final:]
    after = transaction.commit(content, lambda value: _assert_stat_delta(before, value, "tracks", 1))
    return {"ok": True, "transaction_id": transaction.transaction_id, "snapshot_id": snapshot["id"],
            "diff": _diff(before, after), "verification": run_check("drc", path)}


def move_footprint(board: str | Path, reference: str, x: float, y: float, rotation: float | None = None, expected_sha256: str | None = None, backend: str = "file") -> dict[str, Any]:
    """Move one footprint by its reference without rewriting unrelated board data."""
    if not all(math.isfinite(value) for value in (x, y)) or (rotation is not None and not math.isfinite(rotation)):
        raise KiClawError("footprint position and rotation must be finite numbers")
    policy = pcb_backend_policy(board, backend)
    if backend == "auto" and policy["selected"] == "ipc":
        return ipc_move_footprint(board, reference, x, y, rotation, expected_sha256)
    if backend == "ipc":
        return ipc_move_footprint(board, reference, x, y, rotation, expected_sha256)
    path = resolve_path(board, ".kicad_pcb")
    pre_summary = board_summary(path)
    pre_text = path.read_text(encoding="utf-8")
    before_sha256 = pre_summary["sha256"]
    if not any(f'(property "Reference" "{reference}"' in form for form in _top_level_forms(pre_text, "footprint")):
        raise KiClawError(f"Footprint reference not found: {reference}")
    transaction = begin_transaction(path, "move_footprint", expected_sha256 or before_sha256)
    before = transaction.before_summary
    text = transaction.before_content
    forms = _top_level_forms(text, "footprint")
    selected = next((form for form in forms if f'(property "Reference" "{reference}"' in form), None)
    if selected is None:
        raise KiClawError(f"Footprint reference not found: {reference}")
    at = re.search(r"\(at\s+-?[\d.]+\s+-?[\d.]+(?:\s+-?[\d.]+)?\)", selected)
    if at is None:
        raise KiClawError(f"Footprint {reference} has no editable position")
    old_at = at.group(0)
    values = old_at.removeprefix("(at").removesuffix(")").split()
    angle = rotation if rotation is not None else (float(values[2]) if len(values) == 3 else None)
    new_at = f"(at {x} {y}" + (f" {angle}" if angle is not None else "") + ")"
    snapshot = transaction.take_snapshot("before-move-footprint")
    content = text.replace(selected, selected.replace(old_at, new_at, 1), 1)
    def verify_move(value: dict[str, Any]) -> None:
        moved = next((item for item in value["footprints"] if item["reference"] == reference), None)
        if moved is None or moved["at"] is None or abs(moved["at"][0] - x) > 1e-9 or abs(moved["at"][1] - y) > 1e-9:
            raise KiClawError(f"Post-write verification failed for footprint {reference}")
    after = transaction.commit(content, verify_move)
    return {"ok": True, "transaction_id": transaction.transaction_id, "snapshot_id": snapshot["id"],
            "diff": _diff(before, after), "verification": run_check("drc", path)}


def _assert_stat_delta(before: dict[str, Any], after: dict[str, Any], key: str, delta: int) -> None:
    if after["statistics"].get(key) != before["statistics"].get(key, 0) + delta:
        raise KiClawError(f"Post-write verification failed: expected {key} to change by {delta}")
