#!/usr/bin/env python3
"""Utilities for reading module/config metadata from config/modules.json.

The file is stored as JSON-compatible YAML so we can parse it with Python's
standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
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
        native_paths = module.get("native_paths")
        if native_paths is not None and not isinstance(native_paths, list):
            raise ValueError(f"modules[{idx}] 'native_paths' must be a list")
        for jdx, entry in enumerate(module["configs"]):
            if not isinstance(entry, dict):
                raise ValueError(f"modules[{idx}].configs[{jdx}] must be an object")
            primary = entry.get("primary")
            if primary is not None and not isinstance(primary, bool):
                raise ValueError(
                    f"modules[{idx}].configs[{jdx}] 'primary' must be a boolean"
                )

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


def requested_artifact_names(
    data: dict[str, Any],
    board: str | None = None,
    only_modules: list[str] | None = None,
) -> list[str]:
    """Return artifact names, optionally restricted to *only_modules*."""
    return [
        str(module["artifact"])
        for module in data.get("modules", [])
        if not _is_excluded(module, board)
        and (only_modules is None or str(module["name"]) in only_modules)
    ]


def _artifact_selection(
    data: dict[str, Any], board: str | None, only_modules: str | None
) -> list[str]:
    only: list[str] | None = None
    if only_modules:
        only = [m.strip() for m in only_modules.split(",") if m.strip()]
    return requested_artifact_names(data, board, only)


# ---------------------------------------------------------------------------
# Build planning – decide what actually needs to be compiled
# ---------------------------------------------------------------------------

STATUS_SKIPPED = "skipped"
STATUS_RESHIPPED = "reshipped"
STATUS_BUILD = "build"
STATUS_EXCLUDED = "excluded"

STATUS_ICONS = {
    STATUS_SKIPPED: "⏭️",
    STATUS_RESHIPPED: "♻️",
    STATUS_BUILD: "✅",
    STATUS_EXCLUDED: "⚪",
}


def _bool_label(value: Any) -> str:
    return "true" if value else "false"


_KCONFIG_ASSIGNMENT = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(.*)$")
_KCONFIG_UNSET = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")


def parse_kernel_config(path: str | Path) -> dict[str, str]:
    """Parse a kernel .config into a symbol → value mapping.

    Symbols that are commented out ("# CONFIG_FOO is not set") map to "n".
    """
    values: dict[str, str] = {}
    with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            unset = _KCONFIG_UNSET.match(line)
            if unset:
                values[unset.group(1)] = "n"
                continue
            assignment = _KCONFIG_ASSIGNMENT.match(line)
            if assignment:
                values[assignment.group(1)] = assignment.group(2).strip().strip('"')
    return values


def primary_symbol(module: dict[str, Any]) -> str:
    """Return the symbol that decides whether the module itself is available."""
    configs = module.get("configs", [])
    for entry in configs:
        if entry.get("primary"):
            return str(entry["symbol"])
    for entry in configs:
        if str(entry["symbol"]) == f"CONFIG_{str(module['name']).upper()}":
            return str(entry["symbol"])
    return str(configs[0]["symbol"])


def _satisfied(have: str, want: str) -> bool:
    """Return True when *have* already provides everything *want* asks for."""
    if want == "y":
        return have == "y"
    if want == "m":
        return have in {"m", "y"}
    return have == want


def _config_diffs(
    module: dict[str, Any], kernel_config: dict[str, str]
) -> list[dict[str, str]]:
    diffs: list[dict[str, str]] = []
    for entry in module.get("configs", []):
        if entry.get("type") == "string":
            continue
        symbol = str(entry["symbol"])
        want = str(entry["value"])
        have = kernel_config.get(symbol, "n")
        if not _satisfied(have, want):
            diffs.append({"symbol": symbol, "haos": have, "requested": want})
    return diffs


def plan_module(
    module: dict[str, Any],
    kernel_config: dict[str, str],
    linux_src: Path | None = None,
) -> dict[str, Any]:
    """Classify one module against the kernel config HAOS builds.

    * skipped    – the module is already provided by the official
                   distribution (built into vmlinux, or shipped as a .ko).
    * reshipped  – the .ko exists in the distribution but with a different
                   config, so it has to be rebuilt and re-shipped.
    * build      – the module (or its source) is not part of the kernel.
    """
    symbol = primary_symbol(module)
    have = kernel_config.get(symbol, "n")
    diffs = _config_diffs(module, kernel_config)

    native = False
    if linux_src is not None:
        native = any(
            (Path(linux_src) / rel).exists() for rel in module.get("native_paths", [])
        )

    if native:
        status = STATUS_SKIPPED
        note = "already part of the HAOS kernel sources"
    elif have == "y":
        status = STATUS_SKIPPED
        note = f"built into the HAOS kernel ({symbol}=y)"
        if diffs:
            note += "; requested config cannot be applied to a built-in module"
    elif have == "m":
        if diffs:
            status = STATUS_RESHIPPED
            note = f"HAOS ships {module['artifact']} with a different config"
        else:
            status = STATUS_SKIPPED
            note = f"already shipped by HAOS ({symbol}=m)"
    else:
        status = STATUS_BUILD
        note = "not present in the HAOS kernel"

    return {
        "status": status,
        "note": note,
        "diffs": diffs,
        "primary": symbol,
        "haos_primary": have,
    }


def plan_build(
    data: dict[str, Any],
    board: str,
    kernel_config: dict[str, str],
    linux_src: Path | None = None,
    version: str = "",
) -> dict[str, Any]:
    """Return the full per-board build plan for *board*."""
    modules: dict[str, dict[str, Any]] = {}
    build: list[str] = []
    base_build: list[str] = []
    patched_build: list[str] = []

    for module in data.get("modules", []):
        name = str(module["name"])
        if _is_excluded(module, board):
            modules[name] = {
                "status": STATUS_EXCLUDED,
                "note": str(
                    module.get("exclude_reason", "Not supported on this board.")
                ),
                "diffs": [],
                "primary": primary_symbol(module),
                "haos_primary": "",
            }
            continue

        entry = plan_module(module, kernel_config, linux_src)
        entry["artifact"] = str(module["artifact"])
        entry["requires_patch"] = bool(module.get("requires_patch", False))
        modules[name] = entry

        if entry["status"] in {STATUS_BUILD, STATUS_RESHIPPED}:
            build.append(name)
            if entry["requires_patch"]:
                patched_build.append(name)
            else:
                base_build.append(name)

    return {
        "board": board,
        "version": version,
        "modules": modules,
        "build": build,
        "base_build": base_build,
        "patched_build": patched_build,
        "need_quic": "quic" in build,
        "need_zfs": "zfs" in build,
        "all_skipped": not build,
    }


def plan_summary_markdown(plan: dict[str, Any]) -> str:
    """Render a build plan as a markdown block for $GITHUB_STEP_SUMMARY."""
    version = plan.get("version") or "latest"
    board = plan.get("board", "")
    lines = [
        f"### Module plan – HAOS {version} / `{board}`",
        "",
        "| Module | Status | Detail |",
        "|:-------|:-------|:-------|",
    ]
    for name, entry in plan.get("modules", {}).items():
        icon = STATUS_ICONS.get(entry["status"], entry["status"])
        detail = entry.get("note", "")
        if entry.get("diffs") and entry["status"] == STATUS_RESHIPPED:
            detail = _format_diffs(entry["diffs"])
        lines.append(f"| `{name}` | {icon} {entry['status']} | {detail} |")

    if plan.get("all_skipped"):
        lines += [
            "",
            "All requested modules are already provided by the official HAOS "
            "distribution for this board – nothing to compile.",
        ]
    lines.append("")
    return "\n".join(lines)


def _format_diffs(diffs: list[dict[str, str]]) -> str:
    parts = []
    for diff in diffs:
        parts.append(
            f"`{diff['symbol']}` "
            f"{_diff_value(diff['haos'])} → {_diff_value(diff['requested'])}"
        )
    return ", ".join(parts)


def _diff_value(value: str) -> str:
    return "unset" if value in {"", "n"} else f"`{value}`"


def aggregate_statuses(manifest_paths: list[str]) -> str:
    """Merge per-board statuses from manifests into module → board → status."""
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for path in manifest_paths:
        with open(path) as fh:
            data = json.load(fh)
        board = str(data.get("board", ""))
        for module, entry in data.get("statuses", {}).items():
            result.setdefault(module, {})[board] = entry
    return json.dumps(result, sort_keys=True)


def write_manifest(
    plan: dict[str, Any],
    version: str,
    board: str,
    quic_outcome: str = "",
    zfs_outcome: str = "",
) -> dict[str, Any]:
    """Build the per-board build manifest, including planned statuses."""
    statuses = {
        name: {
            "status": entry["status"],
            "note": entry.get("note", ""),
            "diffs": entry.get("diffs", []),
        }
        for name, entry in plan.get("modules", {}).items()
    }
    failed: dict[str, str] = {}
    for name, outcome in (("quic", quic_outcome), ("zfs", zfs_outcome)):
        if outcome == "failure":
            failed[name] = board
    return {
        "board": board,
        "version": version,
        "statuses": statuses,
        "failed": failed,
    }


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
    statuses: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> str:
    """Build a module×board matrix table with a numbered legend."""
    if failed_modules is None:
        failed_modules = {}
    if statuses is None:
        statuses = {}

    legend_entries: list[tuple[str, str]] = []
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

    def _get_config_ref(module_name: str, board: str, entry: dict[str, Any]) -> int:
        key = f"__cfg__{module_name}__{board}"
        if key not in reason_index:
            reason_index[key] = len(legend_entries) + 1
            diffs = entry.get("diffs", [])
            detail = _format_diffs(diffs) if diffs else entry.get("note", "")
            if entry.get("status") == STATUS_RESHIPPED:
                icon = ":recycle:"
                prefix = "reshipped with different config"
            else:
                icon = ":fast_forward:"
                prefix = "already available, config not applied"
            legend_entries.append(
                (icon, f"`{module_name}` @ `{board}`: {prefix} – {detail}")
            )
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
                continue
            if board in excluded_boards:
                ref = _get_exclude_ref(exclude_reason)
                cells.append(f":white_circle: <sup>{ref}</sup>")
                continue

            entry = statuses.get(name, {}).get(board)
            if entry is None:
                # No build information for this board – assume available.
                cells.append(":white_check_mark:")
                continue

            status = entry.get("status")
            if status == STATUS_SKIPPED:
                if entry.get("diffs"):
                    ref = _get_config_ref(name, board, entry)
                    cells.append(f":fast_forward: <sup>{ref}</sup>")
                else:
                    cells.append(":fast_forward:")
            elif status == STATUS_RESHIPPED:
                ref = _get_config_ref(name, board, entry)
                cells.append(f":recycle: <sup>{ref}</sup>")
            elif status == STATUS_EXCLUDED:
                ref = _get_exclude_ref(entry.get("note") or exclude_reason)
                cells.append(f":white_circle: <sup>{ref}</sup>")
            else:
                cells.append(":white_check_mark:")
        rows.append(f"| `{artifact}` | " + " | ".join(cells) + " |")

    legend_lines = [
        "",
        "| | |",
        "|:---|:---|",
        "| :white_check_mark: | Built and shipped from this repository |",
        "| :recycle: | Reshipped – already in the official distribution, but with a different config |",
        "| :fast_forward: | Skipped – already available in the official distribution |",
    ]
    for idx, (icon, reason) in enumerate(legend_entries, start=1):
        legend_lines.append(f"| {icon} <sup>{idx}</sup> | {reason} |")

    return "\n".join([header, separator, *rows, *legend_lines, ""])


def release_body(
    version: str,
    data: dict[str, Any],
    boards: list[str],
    failed_modules: dict[str, list[str]] | None = None,
    statuses: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> str:
    matrix = _build_matrix_table(data, boards, failed_modules, statuses)
    body = (
        "Compiled out-of-tree kernel modules for **Home Assistant OS "
        f"{version}**.\n\n"
        "Artifacts are named `{{module}}_{{haos_version}}_{{board}}.ko`.\n\n"
        "Top-level modules listed below are requested explicitly from "
        "`config/modules.json`. Any additional `.ko` files required by those "
        "modules are discovered from the built tree with `modinfo` and are "
        "attached automatically only when the full dependency set is present.\n\n"
        "Modules that HAOS already provides (built into the kernel, or shipped "
        "as a `.ko` of its own) are not rebuilt; modules it provides with a "
        "different config are reshipped and the config difference is noted "
        "in the legend.\n\n"
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

    artifacts = sub.add_parser("artifact-names", help="Print artifact basenames, one per line")
    artifacts.add_argument("--only-modules", default=None)
    artifacts_json = sub.add_parser(
        "artifact-names-json", help="Print artifact basenames as JSON array"
    )
    artifacts_json.add_argument("--only-modules", default=None)

    plan = sub.add_parser(
        "plan-status",
        help="Classify every module against the kernel config HAOS builds",
    )
    plan.add_argument("--kernel-config", required=True,
                      help="Path to the merged kernel .config")
    plan.add_argument("--linux-src", default=None,
                      help="Kernel source tree, used to detect natively integrated modules")
    plan.add_argument("--version", default="", help="HAOS version (informational)")
    plan.add_argument("--json-out", default=None, help="Write the plan JSON here")
    plan.add_argument("--summary-out", default=None,
                      help="Append a markdown summary (e.g. $GITHUB_STEP_SUMMARY)")
    plan.add_argument("--github-output", default=None,
                      help="Write step outputs (e.g. $GITHUB_OUTPUT)")

    manifest = sub.add_parser(
        "write-manifest", help="Write a per-board build manifest from a plan"
    )
    manifest.add_argument("--plan", required=True, help="Path to the plan JSON")
    manifest.add_argument("--version", required=True, help="HAOS version")
    manifest.add_argument("--board", required=True, help="Target board")
    manifest.add_argument("--quic-outcome", default="", help="Step outcome for quic")
    manifest.add_argument("--zfs-outcome", default="", help="Step outcome for zfs")
    manifest.add_argument("--output", required=True, help="Path of the manifest file")

    agg = sub.add_parser(
        "aggregate-statuses",
        help="Aggregate module statuses from build manifests",
    )
    agg.add_argument("manifest_paths", nargs="+", help="Paths to build manifests")

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
    body.add_argument(
        "--statuses-json",
        default=None,
        help="JSON object module → board → {status, note, diffs} from the build manifests",
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
        print("\n".join(_artifact_selection(data, board, args.only_modules)))
        return 0

    if args.command == "artifact-names-json":
        print(json.dumps(_artifact_selection(data, board, args.only_modules)))
        return 0

    if args.command == "plan-status":
        if not board:
            parser.error("plan-status requires --board")
        kernel_config = parse_kernel_config(args.kernel_config)
        plan = plan_build(
            data,
            board,
            kernel_config,
            Path(args.linux_src) if args.linux_src else None,
            version=args.version,
        )
        payload = json.dumps(plan, indent=2, sort_keys=True)
        if args.json_out:
            Path(args.json_out).write_text(payload + "\n", encoding="utf-8")
        print(payload)

        if args.summary_out:
            with Path(args.summary_out).open("a", encoding="utf-8") as fh:
                fh.write(plan_summary_markdown(plan) + "\n")

        if args.github_output:
            outputs = {
                "build_modules": ",".join(plan["build"]),
                "base_build": ",".join(plan["base_build"]),
                "patched_build": ",".join(plan["patched_build"]),
                "need_quic": _bool_label(plan["need_quic"]),
                "need_zfs": _bool_label(plan["need_zfs"]),
                "all_skipped": _bool_label(plan["all_skipped"]),
            }
            with Path(args.github_output).open("a", encoding="utf-8") as fh:
                for key, value in outputs.items():
                    fh.write(f"{key}={value}\n")
        return 0

    if args.command == "write-manifest":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        manifest = write_manifest(
            plan,
            version=args.version,
            board=args.board,
            quic_outcome=args.quic_outcome,
            zfs_outcome=args.zfs_outcome,
        )
        text = json.dumps(manifest, indent=2, sort_keys=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0

    if args.command == "aggregate-statuses":
        print(aggregate_statuses(args.manifest_paths))
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
        statuses: dict[str, dict[str, dict[str, Any]]] | None = None
        if args.statuses_json:
            statuses = json.loads(args.statuses_json)
        body = release_body(
            args.version,
            data,
            boards=boards_list,
            failed_modules=failed,
            statuses=statuses,
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
