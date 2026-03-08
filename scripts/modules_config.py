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

    return data


def normalize_assignments(data: dict[str, Any]) -> list[dict[str, str]]:
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
        for entry in module.get("configs", []):
            add_entry(entry)

    return assignments


def module_names(data: dict[str, Any]) -> list[str]:
    return [str(module["name"]) for module in data.get("modules", [])]


def module_rows(data: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for module in data.get("modules", []):
        artifact = str(module["artifact"])
        description = str(module["description"])
        rows.append(f"| `{artifact}` | {description} |")
    return rows


def release_body(version: str, data: dict[str, Any]) -> str:
    rows = "\n".join(module_rows(data))
    return (
        "Compiled out-of-tree kernel modules for **Home Assistant OS "
        f"{version}**.\n\n"
        "Artifacts are named `{module}_{haos_version}_{board}.ko`.\n\n"
        "### Included modules\n"
        "| Module | Description |\n"
        "|:--------|:-------------|\n"
        f"{rows}\n\n"
        "### Supported boards\n"
        "One set of `.ko` files is provided per board listed below.\n"
        "Each file is compiled against the **exact** kernel shipped with\n"
        f"HAOS {version} for that board.  Loading a module on a\n"
        "different kernel version will fail.\n\n"
        "See the README for installation instructions.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read module build config")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to modules.yml (JSON-compatible YAML)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("module-names", help="Print module names, one per line")
    sub.add_parser("module-names-json", help="Print module names as JSON array")
    sub.add_parser(
        "config-assignments-json",
        help="Print CONFIG assignments as JSON",
    )
    sub.add_parser("module-table-rows", help="Print markdown rows for module table")

    body = sub.add_parser("release-body", help="Render release body markdown")
    body.add_argument("--version", required=True, help="HAOS version")
    body.add_argument("--output", help="Write output to file instead of stdout")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    data = load_config(Path(args.config))

    if args.command == "module-names":
        print("\n".join(module_names(data)))
        return 0

    if args.command == "module-names-json":
        print(json.dumps(module_names(data)))
        return 0

    if args.command == "config-assignments-json":
        print(json.dumps(normalize_assignments(data)))
        return 0

    if args.command == "module-table-rows":
        print("\n".join(module_rows(data)))
        return 0

    if args.command == "release-body":
        body = release_body(args.version, data)
        if args.output:
            Path(args.output).write_text(body, encoding="utf-8")
        else:
            print(body)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
