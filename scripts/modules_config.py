#!/usr/bin/env python3
"""Utilities for reading module/config metadata from config/modules.json.

The file is stored as JSON-compatible YAML so we can parse it with Python's
standard library only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "modules.json"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError("Top-level config must be an object")

    modules = data.get("modules")
    if not isinstance(modules, list):
        raise ValueError("'modules' must be an array")

    for idx, module in enumerate(modules):
        if not isinstance(module, dict):
            raise ValueError(f"modules[{idx}] must be an object")
        for key in ("name", "artifact", "description", "configs"):
            if key not in module:
                raise ValueError(f"modules[{idx}] missing '{key}'")
        exclude_boards = module.get("exclude_boards")
        if exclude_boards is not None and not isinstance(exclude_boards, list):
            raise ValueError(f"modules[{idx}] 'exclude_boards' must be a list")
        exclude_reason = module.get("exclude_reason")
        if exclude_reason is not None and not isinstance(exclude_reason, str):
            raise ValueError(f"modules[{idx}] 'exclude_reason' must be a string")
        requires_patch = module.get("requires_patch")
        if requires_patch is not None and not isinstance(requires_patch, bool):
            raise ValueError(f"modules[{idx}] 'requires_patch' must be a boolean")

    return data


def _is_excluded(module: dict[str, Any], board: str | None) -> bool:
    """Return True when *module* should be skipped for *board*."""
    if board is None:
        return False
    return board in module.get("exclude_boards", [])


def normalize_assignments(
    data: dict[str, Any],
    board: str | None = None,
    only_modules: list[str] | None = None,
) -> list[dict[str, str]]:
    assignments: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_entry(entry: Any) -> None:
        if not isinstance(entry, dict):
            raise ValueError("Config entries must be objects")

        symbol = entry.get("symbol")
        value = entry.get("value")
        value_type = entry.get("type", "literal")

        if not isinstance(symbol, str) or not symbol.startswith("CONFIG_"):
            raise ValueError(f"Invalid symbol: {symbol!r}")
        if not isinstance(value, str):
            raise ValueError(f"Invalid value for {symbol}: {value!r}")
        if value_type not in {"literal", "string"}:
            raise ValueError(f"Invalid type for {symbol}: {value_type!r}")

        if symbol in seen:
            return
        seen.add(symbol)
        assignments.append({"symbol": symbol, "value": value, "type": value_type})

    for entry in data.get("base_configs", []):
        add_entry(entry)

    modules = data.get("modules", [])
    for module in modules:
        if _is_excluded(module, board):
            continue
        if only_modules is not None and str(module["name"]) not in only_modules:
            continue
        for entry in module.get("configs", []):
            add_entry(entry)

    return assignments


def module_names(data: dict[str, Any], board: str | None = None) -> list[str]:
    return [
        str(module["name"])
        for module in data.get("modules", [])
        if not _is_excluded(module, board)
    ]


def base_module_names(data: dict[str, Any], board: str | None = None) -> list[str]:
    """Return module names that do NOT require kernel source patching."""
    return [
        str(m["name"])
        for m in data.get("modules", [])
        if not _is_excluded(m, board) and not m.get("requires_patch", False)
    ]


def patched_module_names(data: dict[str, Any], board: str | None = None) -> list[str]:
    """Return module names that require kernel source patching."""
    return [
        str(m["name"])
        for m in data.get("modules", [])
        if not _is_excluded(m, board) and m.get("requires_patch", False)
    ]


def artifact_names(data: dict[str, Any], board: str | None = None) -> list[str]:
    return [
        str(module["artifact"])
        for module in data.get("modules", [])
        if not _is_excluded(module, board)
    ]


def _exclusion_note(module: dict[str, Any]) -> str:
    """Return a human-readable note about board exclusions, or empty string."""
    boards = module.get("exclude_boards", [])
    if not boards:
        return ""
    reason = module.get("exclude_reason", "Not supported on these boards.")
    boards_fmt = ", ".join(f"`{b}`" for b in boards)
    return f"⚠️ Not available on {boards_fmt}: {reason}"


def module_rows(data: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for module in data.get("modules", []):
        artifact = str(module["artifact"])
        description = str(module["description"])
        note = _exclusion_note(module)
        rows.append(f"| `{artifact}` | {description} | {note} |")
    return rows


def _build_matrix_table(
    data: dict[str, Any],
    boards: list[str],
    failed_modules: dict[str, list[str]] | None = None,
) -> str:
    """Build a module×board matrix table with a numbered legend."""
    if failed_modules is None:
        failed_modules = {}

    legend_entries: list[tuple[str, str]]  = []
    reason_index: dict[str, int] = {}

    def _get_exclude_ref(reason: str) -> int:
        if reason not in reason_index:
            reason_index[reason] = len(legend_entries) + 1
            legend_entries.append((":white_circle:", reason))
        return reason_index[reason]

    def _get_failure_ref(module_name: str) -> int:
        key = f"__fail__{module_name}"
        if key not in reason_index:
            reason_index[key] = len(legend_entries) + 1
            legend_entries.append((":anger:", f"`{module_name}` build error"))
        return reason_index[key]

    modules = data.get("modules", [])

    header = "| Module | " + " | ".join(f"`{b}`" for b in boards) + " |"
    separator = "|:-------|" + "|".join(":---:" for _ in boards) + "|"

    rows: list[str] = []
    for module in modules:
        name = str(module["name"])
        artifact = str(module["artifact"])
        excluded_boards = module.get("exclude_boards", [])
        exclude_reason = module.get(
            "exclude_reason", "Not supported on this board."
        )
        failed_boards = failed_modules.get(name, [])

        cells: list[str] = []
        for board in boards:
            if board in failed_boards:
                ref = _get_failure_ref(name)
                cells.append(f":anger: <sup>{ref}</sup>")
            elif board in excluded_boards:
                ref = _get_exclude_ref(exclude_reason)
                cells.append(f":white_circle: <sup>{ref}</sup>")
            else:
                cells.append(":white_check_mark:")
        rows.append(f"| `{artifact}` | " + " | ".join(cells) + " |")

    legend_lines = [
        "",
        "| | |",
        "|:---|:---|",
        "| :white_check_mark: | Module Available |",
    ]
    for idx, (icon, reason) in enumerate(legend_entries, start=1):
        legend_lines.append(f"| {icon} <sup>{idx}</sup> | {reason} |")

    return "\n".join([header, separator, *rows, *legend_lines, ""])


def release_body(
    version: str,
    data: dict[str, Any],
    boards: list[str],
    failed_modules: dict[str, list[str]] | None = None,
) -> str:
    matrix = _build_matrix_table(data, boards, failed_modules)
    body = (
        "Compiled out-of-tree kernel modules for **Home Assistant OS "
        f"{version}**.\n\n"
        "Artifacts are named `{{module}}_{{haos_version}}_{{board}}.ko`.\n\n"
        "Top-level modules listed below are requested explicitly from "
        "`config/modules.json`. Any additional `.ko` files required by those "
        "modules are discovered from the built tree with `modinfo` and are "
        "attached automatically only when the full dependency set is present.\n\n"
        "### Included modules\n\n"
        f"{matrix}\n"
        "### Supported boards\n\n"
        "One set of `.ko` files is provided per board listed below.\n"
        "Each file is compiled against the **exact** kernel shipped with\n"
        f"HAOS {version} for that board.  Loading a module on a\n"
        "different kernel version will fail.\n\n"
        "See the README for installation instructions.\n"
    )
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read module build config")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to modules.yml (JSON-compatible YAML)",
    )
    parser.add_argument(
        "--board",
        default=None,
        help="Target board name; modules with this board in 'exclude_boards' are skipped",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("module-names", help="Print module names, one per line")
    sub.add_parser("module-names-json", help="Print module names as JSON array")
    sub.add_parser("base-module-names", help="Print base (non-patched) module names, one per line")
    sub.add_parser("base-module-names-json", help="Print base module names as JSON array")
    sub.add_parser("patched-module-names", help="Print patched module names, one per line")
    sub.add_parser("patched-module-names-json", help="Print patched module names as JSON array")
    sub.add_parser("artifact-names", help="Print artifact basenames, one per line")
    sub.add_parser("artifact-names-json", help="Print artifact basenames as JSON array")

    assignments = sub.add_parser(
        "config-assignments-json",
        help="Print CONFIG assignments as JSON",
    )
    assignments.add_argument(
        "--only-modules",
        default=None,
        help="Comma-separated list of module names to include (default: all)",
    )

    sub.add_parser("module-table-rows", help="Print markdown rows for module table")

    body = sub.add_parser("release-body", help="Render release body markdown")
    body.add_argument("--version", required=True, help="HAOS version")
    body.add_argument("--output", help="Write output to file instead of stdout")
    body.add_argument(
        "--boards-json",
        required=True,
        help='JSON array of board names, e.g. \'["generic_x86_64","rpi4_64"]\'',
    )
    body.add_argument(
        "--failed-modules-json",
        default=None,
        help='JSON object mapping module names to lists of failed boards, e.g. \'{"quic":["generic_x86_64"]}\'',
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    data = load_config(Path(args.config))
    board: str | None = args.board

    if args.command == "module-names":
        print("\n".join(module_names(data, board)))
        return 0

    if args.command == "module-names-json":
        print(json.dumps(module_names(data, board)))
        return 0

    if args.command == "base-module-names":
        print("\n".join(base_module_names(data, board)))
        return 0

    if args.command == "base-module-names-json":
        print(json.dumps(base_module_names(data, board)))
        return 0

    if args.command == "patched-module-names":
        print("\n".join(patched_module_names(data, board)))
        return 0

    if args.command == "patched-module-names-json":
        print(json.dumps(patched_module_names(data, board)))
        return 0

    if args.command == "artifact-names":
        print("\n".join(artifact_names(data, board)))
        return 0

    if args.command == "artifact-names-json":
        print(json.dumps(artifact_names(data, board)))
        return 0

    if args.command == "config-assignments-json":
        only: list[str] | None = None
        if args.only_modules:
            only = [m.strip() for m in args.only_modules.split(",") if m.strip()]
        print(json.dumps(normalize_assignments(data, board, only_modules=only)))
        return 0

    if args.command == "module-table-rows":
        print("\n".join(module_rows(data)))
        return 0

    if args.command == "release-body":
        boards_list: list[str] = json.loads(args.boards_json)
        failed: dict[str, list[str]] | None = None
        if args.failed_modules_json:
            failed = json.loads(args.failed_modules_json)
        body = release_body(
            args.version, data, boards=boards_list, failed_modules=failed
        )
        if args.output:
            Path(args.output).write_text(body, encoding="utf-8")
        else:
            print(body)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
