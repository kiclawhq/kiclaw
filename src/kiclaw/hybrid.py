"""Hybrid-live glue: attach post-edit narration + visual update to mutation results."""

from __future__ import annotations

import os
from typing import Any, Callable

from .visual_update import narrate_mutation

# tool_name -> (path argument names in order of preference, summary builder)
_PathNames = tuple[str, ...]
_SummaryFn = Callable[[dict[str, Any], dict[str, Any]], str]

MUTATION_TOOLS: dict[str, tuple[_PathNames, _SummaryFn]] = {
    "move_footprint": (
        ("board",),
        lambda a, r: f"Moved footprint `{a.get('reference')}` to ({a.get('x')}, {a.get('y')}).",
    ),
    "rotate_footprint": (
        ("board",),
        lambda a, r: f"Rotated footprint `{a.get('reference')}` to {a.get('rotation')}°.",
    ),
    "add_track": (
        ("board",),
        lambda a, r: f"Added track on net `{a.get('net_name')}` from ({a.get('start_x')},{a.get('start_y')}) to ({a.get('end_x')},{a.get('end_y')}).",
    ),
    "add_via": (
        ("board",),
        lambda a, r: f"Added via on net `{a.get('net_name')}` at ({a.get('x')}, {a.get('y')}).",
    ),
    "delete_track": (
        ("board",),
        lambda a, r: "Deleted a copper track segment.",
    ),
    "delete_via": (
        ("board",),
        lambda a, r: f"Deleted via near ({a.get('x')}, {a.get('y')}).",
    ),
    "delete_footprint": (
        ("board",),
        lambda a, r: f"Deleted footprint `{a.get('reference')}`.",
    ),
    "place_footprint": (
        ("board",),
        lambda a, r: f"Placed footprint `{a.get('new_reference')}` (cloned from `{a.get('source_reference')}`).",
    ),
    "set_footprint_property": (
        ("board",),
        lambda a, r: f"Set `{a.get('property_name')}` on `{a.get('reference')}` to `{a.get('value')}`.",
    ),
    "create_zone": (
        ("board",),
        lambda a, r: f"Created copper zone on net `{a.get('net_name')}` ({a.get('layer')}).",
    ),
    "add_wire": (
        ("schematic",),
        lambda a, r: f"Added schematic wire from ({a.get('start_x')},{a.get('start_y')}) to ({a.get('end_x')},{a.get('end_y')}).",
    ),
    "delete_wire": (
        ("schematic",),
        lambda a, r: "Deleted a schematic wire.",
    ),
    "add_component": (
        ("schematic",),
        lambda a, r: f"Added component `{a.get('reference')}` ({a.get('lib_id')}).",
    ),
    "add_custom_component": (
        ("schematic",),
        lambda a, r: f"Added custom component `{a.get('reference')}` as `{a.get('new_lib_id')}`.",
    ),
    "delete_component": (
        ("schematic",),
        lambda a, r: f"Deleted component `{a.get('reference')}`.",
    ),
    "move_component": (
        ("schematic",),
        lambda a, r: f"Moved component `{a.get('reference')}` to ({a.get('x')}, {a.get('y')}).",
    ),
    "rotate_component": (
        ("schematic",),
        lambda a, r: f"Rotated component `{a.get('reference')}` to {a.get('rotation')}°.",
    ),
    "set_component_value": (
        ("schematic",),
        lambda a, r: f"Set value of `{a.get('reference')}` to `{a.get('value')}`.",
    ),
    "add_net_label": (
        ("schematic",),
        lambda a, r: f"Added net label `{a.get('name')}`.",
    ),
    "ipc_move_footprint": (
        ("board",),
        lambda a, r: f"Live-moved footprint `{a.get('reference')}` (IPC).",
    ),
    "place_power_symbol": (
        ("schematic",),
        lambda a, r: f"Placed power symbol `{a.get('reference') or a.get('power_name') or 'PWR'}` on schematic.",
    ),
    "fill_zones": (
        ("board",),
        lambda a, r: "Filled copper zones on board (file-backed).",
    ),
    "lock_footprint": (
        ("board",),
        lambda a, r: f"Locked footprint `{a.get('reference')}`.",
    ),
    "unlock_footprint": (
        ("board",),
        lambda a, r: f"Unlocked footprint `{a.get('reference')}`.",
    ),
}


def attach_hybrid_live(
    tool_name: str,
    arguments: dict[str, Any] | None,
    result: Any,
) -> Any:
    """If result is a successful mutation dict, attach hybrid-live narration + visual update."""
    if tool_name not in MUTATION_TOOLS:
        return result
    if not isinstance(result, dict):
        return result
    if result.get("ok") is False:
        return result

    args = arguments or {}
    path_keys, summary_fn = MUTATION_TOOLS[tool_name]
    path = None
    for key in path_keys:
        if args.get(key):
            path = args[key]
            break
    if path is None:
        path = result.get("board") or result.get("schematic") or result.get("path")

    try:
        summary = summary_fn(args, result)
    except Exception:
        summary = f"Completed `{tool_name}`."

    verification = result.get("verification")
    verification_ok = None
    if isinstance(verification, dict):
        verification_ok = verification.get("ok")
    elif "verification" in result:
        verification_ok = None

    look_at = None
    if args.get("reference"):
        look_at = f"component/footprint `{args['reference']}` on the canvas"
    elif path:
        look_at = f"updated file `{path}` — reload in KiCad if the view is stale"

    backend = result.get("backend") or ("ipc" if tool_name.startswith("ipc_") else "file")
    # Tests / constrained hosts can set KICLAW_HYBRID_NO_REFRESH=1 to skip IPC probe latency.
    do_refresh = os.environ.get("KICLAW_HYBRID_NO_REFRESH", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }
    try:
        narration = narrate_mutation(
            action=tool_name,
            path=path,
            summary=summary,
            look_at=look_at,
            transaction_id=result.get("transaction_id"),
            snapshot_id=result.get("snapshot_id"),
            verification_ok=verification_ok,
            backend=str(backend),
            refresh=do_refresh,
        )
        result = dict(result)
        result["hybrid_live"] = narration
        result["user_message"] = narration.get("message")
    except Exception as exc:
        result = dict(result)
        result["hybrid_live"] = {
            "ok": False,
            "reason": f"Could not build hybrid narration: {type(exc).__name__}: {exc}",
        }
    return result
