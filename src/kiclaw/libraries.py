"""Symbol and footprint library discovery, search, and project import."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterator

from .core import KiClawError, resolve_path, _atomic_write, _top_level_forms

MACOS_SYMBOLS = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
MACOS_FOOTPRINTS = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")


def _symbol_roots() -> list[Path]:
    roots = []
    for env in ("KICAD_SYMBOL_DIR", "KICAD10_SYMBOL_DIR", "KICAD9_SYMBOL_DIR"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value))
    roots += [MACOS_SYMBOLS, Path.home() / "Documents" / "KiCad" / "10.0" / "symbols"]
    return [p for p in roots if p.is_dir()]


def _footprint_roots() -> list[Path]:
    roots = []
    for env in ("KICAD_FOOTPRINT_DIR", "KICAD10_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value))
    roots += [MACOS_FOOTPRINTS, Path.home() / "Documents" / "KiCad" / "10.0" / "footprints"]
    return [p for p in roots if p.is_dir()]


def _iter_symbol_defs(library_path: Path) -> Iterator[dict[str, Any]]:
    try:
        text = library_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    nickname = library_path.stem
    for form in _top_level_forms(text, "symbol"):
        match = re.match(r'\(symbol\s+"([^"]+)"', form)
        if not match:
            continue
        short = match.group(1)
        # skip unit sub-symbols like "R_0_1"
        if re.search(r"_\d+_\d+$", short) and short.count("_") >= 2:
            # still include extended names; filter pure unit graphics later if parent exists
            pass
        value = re.search(r'\(property\s+"Value"\s+"([^"]*)"', form)
        desc = re.search(r'\(property\s+"Description"\s+"([^"]*)"', form)
        yield {
            "lib_id": f"{nickname}:{short}" if ":" not in short else short,
            "library": nickname,
            "name": short.rsplit(":", 1)[-1],
            "value": value.group(1) if value else None,
            "description": desc.group(1) if desc else None,
            "path": str(library_path),
        }


def _iter_footprints(pretty_dir: Path) -> Iterator[dict[str, Any]]:
    nickname = pretty_dir.name.removesuffix(".pretty")
    for mod in sorted(pretty_dir.glob("*.kicad_mod")):
        try:
            text = mod.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name = mod.stem
        desc = re.search(r'\(descr\s+"([^"]*)"', text) or re.search(r'\(property\s+"Description"\s+"([^"]*)"', text)
        yield {
            "fp_id": f"{nickname}:{name}",
            "library": nickname,
            "name": name,
            "description": desc.group(1) if desc else None,
            "path": str(mod),
        }


def list_symbol_libraries() -> dict[str, Any]:
    libs = []
    for root in _symbol_roots():
        for path in sorted(root.glob("*.kicad_sym")):
            libs.append({"nickname": path.stem, "path": str(path), "root": str(root)})
    return {"ok": True, "libraries": libs, "count": len(libs), "roots": [str(r) for r in _symbol_roots()]}


def list_footprint_libraries() -> dict[str, Any]:
    libs = []
    for root in _footprint_roots():
        for path in sorted(root.glob("*.pretty")):
            if path.is_dir():
                libs.append({"nickname": path.name.removesuffix(".pretty"), "path": str(path), "root": str(root)})
    return {"ok": True, "libraries": libs, "count": len(libs), "roots": [str(r) for r in _footprint_roots()]}


def search_symbols(query: str, limit: int = 50) -> dict[str, Any]:
    needle = query.strip().lower()
    if not needle:
        raise KiClawError("query must not be empty")
    limit = max(1, min(limit, 500))
    matches = []
    for root in _symbol_roots():
        for path in sorted(root.glob("*.kicad_sym")):
            for item in _iter_symbol_defs(path):
                blob = f"{item['lib_id']} {item.get('value') or ''} {item.get('description') or ''}".lower()
                if needle in blob:
                    matches.append(item)
                    if len(matches) >= limit:
                        return {"ok": True, "query": query, "count": len(matches), "matches": matches, "truncated": True}
    return {"ok": True, "query": query, "count": len(matches), "matches": matches, "truncated": False}


def search_footprints(query: str, limit: int = 50) -> dict[str, Any]:
    needle = query.strip().lower()
    if not needle:
        raise KiClawError("query must not be empty")
    limit = max(1, min(limit, 500))
    matches = []
    for root in _footprint_roots():
        for pretty in sorted(root.glob("*.pretty")):
            if not pretty.is_dir():
                continue
            for item in _iter_footprints(pretty):
                blob = f"{item['fp_id']} {item.get('description') or ''}".lower()
                if needle in blob:
                    matches.append(item)
                    if len(matches) >= limit:
                        return {"ok": True, "query": query, "count": len(matches), "matches": matches, "truncated": True}
    return {"ok": True, "query": query, "count": len(matches), "matches": matches, "truncated": False}


def get_symbol_info(lib_id: str) -> dict[str, Any]:
    if ":" not in lib_id:
        raise KiClawError("lib_id must look like Library:Symbol")
    lib, name = lib_id.split(":", 1)
    for root in _symbol_roots():
        path = root / f"{lib}.kicad_sym"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for form in _top_level_forms(text, "symbol"):
            if re.match(r'\(symbol\s+"' + re.escape(name) + r'"', form) or re.match(
                r'\(symbol\s+"' + re.escape(lib_id) + r'"', form
            ):
                props = {m.group(1): m.group(2) for m in re.finditer(r'\(property\s+"([^"]+)"\s+"([^"]*)"', form)}
                pins = re.findall(r'\(pin\s+[^\s]+\s+[^\s]+\s+\(at\s+[^\)]+\)\s+\(length\s+[^\)]+\)\s+\(name\s+"([^"]*)"', form)
                return {
                    "ok": True,
                    "lib_id": lib_id,
                    "path": str(path),
                    "properties": props,
                    "pin_names": pins[:64],
                    "form_bytes": len(form.encode("utf-8")),
                }
    raise KiClawError(f"Symbol not found: {lib_id}")


def get_footprint_info(fp_id: str) -> dict[str, Any]:
    if ":" not in fp_id:
        raise KiClawError("fp_id must look like Library:Footprint")
    lib, name = fp_id.split(":", 1)
    for root in _footprint_roots():
        path = root / f"{lib}.pretty" / f"{name}.kicad_mod"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        pads = re.findall(r'\(pad\s+"([^"]*)"\s+([^\s]+)\s+([^\s]+)', text)
        return {
            "ok": True,
            "fp_id": fp_id,
            "path": str(path),
            "pad_count": len(pads),
            "pads_sample": [{"number": a, "type": b, "shape": c} for a, b, c in pads[:32]],
            "bytes": len(text.encode("utf-8")),
        }
    raise KiClawError(f"Footprint not found: {fp_id}")


def list_project_libraries(project: str | Path) -> dict[str, Any]:
    root = resolve_path(project)
    if root.is_file():
        root = root.parent
    symbols = sorted(root.glob("*.kicad_sym"))
    pretties = sorted(p for p in root.glob("*.pretty") if p.is_dir())
    tables = {
        "sym-lib-table": (root / "sym-lib-table").is_file(),
        "fp-lib-table": (root / "fp-lib-table").is_file(),
    }
    return {
        "ok": True,
        "path": str(root),
        "symbol_libraries": [str(p) for p in symbols],
        "footprint_libraries": [str(p) for p in pretties],
        "tables": tables,
    }


def create_project_library(project: str | Path, nickname: str, kind: str = "symbol") -> dict[str, Any]:
    if not nickname or any(c.isspace() for c in nickname) or '"' in nickname:
        raise KiClawError("nickname must be a non-empty token")
    if kind not in {"symbol", "footprint"}:
        raise KiClawError("kind must be symbol or footprint")
    root = resolve_path(project)
    if root.is_file():
        root = root.parent
    if kind == "symbol":
        path = root / f"{nickname}.kicad_sym"
        if not path.exists():
            _atomic_write(
                path,
                '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "kiclaw")\n\t(generator_version "0.1")\n)\n',
            )
        table = root / "sym-lib-table"
        _ensure_table_entry(table, nickname, f"${{KIPRJMOD}}/{nickname}.kicad_sym", "sym")
        return {"ok": True, "kind": kind, "path": str(path), "table": str(table)}
    path = root / f"{nickname}.pretty"
    path.mkdir(exist_ok=True)
    table = root / "fp-lib-table"
    _ensure_table_entry(table, nickname, f"${{KIPRJMOD}}/{nickname}.pretty", "fp")
    return {"ok": True, "kind": kind, "path": str(path), "table": str(table)}


def _ensure_table_entry(table_path: Path, nickname: str, uri: str, kind: str) -> None:
    if kind == "sym":
        default = "(sym_lib_table\n\t(version 7)\n)\n"
        marker = f'(lib (name "{nickname}")'
    else:
        default = "(fp_lib_table\n\t(version 7)\n)\n"
        marker = f'(lib (name "{nickname}")'
    text = table_path.read_text(encoding="utf-8") if table_path.exists() else default
    if marker in text:
        return
    insertion = text.rfind(")")
    if insertion < 0:
        raise KiClawError(f"Invalid library table: {table_path}")
    entry = f'\t(lib (name "{nickname}") (type "KiCad") (uri "{uri}") (options "") (descr "Managed by KiClaw"))\n'
    _atomic_write(table_path, text[:insertion] + entry + text[insertion:])


def import_symbol_to_project(project: str | Path, lib_id: str, nickname: str | None = None) -> dict[str, Any]:
    info = get_symbol_info(lib_id)
    lib, name = lib_id.split(":", 1)
    nick = nickname or "KiClaw"
    created = create_project_library(project, nick, "symbol")
    library_path = Path(created["path"])
    text = library_path.read_text(encoding="utf-8")
    source_path = Path(info["path"])
    source = source_path.read_text(encoding="utf-8")
    definition = None
    for form in _top_level_forms(source, "symbol"):
        if re.match(r'\(symbol\s+"' + re.escape(name) + r'"', form) or re.match(
            r'\(symbol\s+"' + re.escape(lib_id) + r'"', form
        ):
            definition = form
            break
    if definition is None:
        raise KiClawError(f"Could not extract definition for {lib_id}")
    # rename outer symbol to short name for library file
    definition = re.sub(r'^\(symbol\s+"[^"]+"', f'(symbol "{name}"', definition, count=1)
    if f'(symbol "{name}"' in text:
        return {"ok": True, "already_present": True, "lib_id": f"{nick}:{name}", "library": str(library_path)}
    insertion = text.rfind(")")
    new_text = text[:insertion] + "\t" + definition.replace("\n", "\n\t") + "\n" + text[insertion:]
    _atomic_write(library_path, new_text)
    return {"ok": True, "already_present": False, "lib_id": f"{nick}:{name}", "library": str(library_path), "table": created["table"]}


def import_footprint_to_project(project: str | Path, fp_id: str, nickname: str | None = None) -> dict[str, Any]:
    info = get_footprint_info(fp_id)
    lib, name = fp_id.split(":", 1)
    nick = nickname or "KiClaw"
    created = create_project_library(project, nick, "footprint")
    dest = Path(created["path"]) / f"{name}.kicad_mod"
    shutil.copy2(info["path"], dest)
    return {"ok": True, "fp_id": f"{nick}:{name}", "path": str(dest), "table": created["table"]}
