#!/usr/bin/env python3
"""
scripts/update_readme_modules.py
=================================
Regenerates the module table in README.md from config/modules.json.

The script looks for the sentinel comment pair:

    <!-- MODULE_TABLE_START -->
    … existing table …
    <!-- MODULE_TABLE_END -->

and replaces everything between them with a freshly generated Markdown table.

Usage:
    python3 scripts/update_readme_modules.py [--readme README.md] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modules_config import ModulesConfig, ExcludeKind

# ---------------------------------------------------------------------------
# Sentinel markers in README.md
# ---------------------------------------------------------------------------
TABLE_START = "<!-- MODULE_TABLE_START -->"
TABLE_END   = "<!-- MODULE_TABLE_END -->"

# ---------------------------------------------------------------------------
# Board display order + short labels
# ---------------------------------------------------------------------------
ALL_BOARDS_ORDERED = [
    "x86_64",
    "odroid_c4",
    "odroid_n2",
    "rpi3_64",
    "rpi4_64",
    "rpi5_64",
    "yellow",
]

BOARD_LABEL: dict[str, str] = {
    "x86_64":    "x86_64",
    "odroid_c4": "odroid-c4",
    "odroid_n2": "odroid-n2",
    "rpi3_64":   "rpi3",
    "rpi4_64":   "rpi4",
    "rpi5_64":   "rpi5",
    "yellow":    "yellow",
}


def board_cell(mod, board: str) -> str:
    """Return a Markdown table cell character for a module/board combination."""
    kind = mod.exclude_kind_for(board)
    if kind == ExcludeKind.HARD:
        return "❌"
    if kind == ExcludeKind.SOFT_NEON:
        return "⚠️"   # safe-mode (auto-detected)
    return "✅"


def generate_table(cfg: ModulesConfig) -> str:
    """Generate the full Markdown module table as a string."""
    lines: list[str] = []

    # -----------------------------------------------------------------------
    # Legend
    # -----------------------------------------------------------------------
    lines.append("")
    lines.append("The table below is generated automatically from `config/modules.json`.")
    lines.append("")
    lines.append("Legend:")
    lines.append(
        "✅ Built normally · "
        "⚠️ Built in **safe mode** (no NEON AES acceleration — "
        "auto-detected at build time when `kernel_neon_begin` is `EXPORT_SYMBOL_GPL`) · "
        "❌ Not available (hard exclusion)"
    )
    lines.append("")

    # -----------------------------------------------------------------------
    # Table header
    # -----------------------------------------------------------------------
    board_labels = [BOARD_LABEL.get(b, b) for b in ALL_BOARDS_ORDERED]
    header_cells = ["Module", "Description", "License"] + board_labels + ["Notes"]
    separator    = ["---"] * len(header_cells)

    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("| " + " | ".join(separator)    + " |")

    # -----------------------------------------------------------------------
    # One row per module
    # -----------------------------------------------------------------------
    for mod in cfg.modules:
        # Module name as inline code
        name_cell = f"`{mod.name}.ko`"
        desc_cell = mod.description

        # License badge-style short form
        lic_cell = mod.license.replace("CDDL-1.0", "CDDL").replace("GPL-2.0", "GPL-2")

        # Per-board availability cells
        board_cells = [board_cell(mod, b) for b in ALL_BOARDS_ORDERED]

        # Notes: merge soft_neon info + explicit notes
        notes = cfg.readme_notes_for(mod)

        row = [name_cell, desc_cell, lic_cell] + board_cells + [notes]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # -----------------------------------------------------------------------
    # ZFS safe-mode explanation
    # -----------------------------------------------------------------------
    lines.append("> **About ⚠️ safe mode (ZFS on RPi / Yellow)**")
    lines.append("> ")
    lines.append("> ZFS is licensed as CDDL. On Linux ≥ 6.2 / aarch64 (Raspberry Pi Foundation")
    lines.append("> kernel tree), `kernel_neon_begin` and `kernel_neon_end` are exported as")
    lines.append("> `EXPORT_SYMBOL_GPL`, which makes them inaccessible to CDDL modules.")
    lines.append("> ")
    lines.append("> The build system runs `scripts/probe_gpl_symbols.sh` against the target")
    lines.append("> kernel's `Module.symvers` at compile time:")
    lines.append("> ")
    lines.append("> - If the symbols are **not** GPL-only → ZFS is built normally with NEON")
    lines.append(">   acceleration (AES-NI, SHA extensions).")
    lines.append("> - If they **are** GPL-only → ZFS is built with `--without-neon` and")
    lines.append(">   `-DZFS_NO_TRACEPOINTS`. All functionality is preserved; only hardware")
    lines.append(">   crypto acceleration is disabled (≈ 20–30% slower for AES-heavy workloads).")
    lines.append("> ")
    lines.append("> The `build_info_{version}_{board}.json` asset in each release records")
    lines.append("> `\"zfs_safe_mode\": true/false` so you can verify which mode was used.")
    lines.append("")

    return "\n".join(lines)


def update_readme(readme_path: Path, cfg: ModulesConfig, dry_run: bool = False) -> bool:
    """
    Replace the content between TABLE_START and TABLE_END sentinels in README.md.
    Returns True if the file was changed.
    """
    content = readme_path.read_text(encoding="utf-8")

    start_idx = content.find(TABLE_START)
    end_idx   = content.find(TABLE_END)

    if start_idx == -1 or end_idx == -1:
        print(
            f"ERROR: Could not find sentinel markers in {readme_path}.\n"
            f"Add these lines to README.md where you want the table:\n"
            f"  {TABLE_START}\n"
            f"  {TABLE_END}",
            file=sys.stderr,
        )
        return False

    if start_idx >= end_idx:
        print("ERROR: TABLE_START marker appears after TABLE_END.", file=sys.stderr)
        return False

    new_table = generate_table(cfg)
    new_block = f"{TABLE_START}\n{new_table}\n{TABLE_END}"

    old_block = content[start_idx : end_idx + len(TABLE_END)]
    if old_block == new_block:
        print("README module table is already up to date.", file=sys.stderr)
        return False

    new_content = content[:start_idx] + new_block + content[end_idx + len(TABLE_END):]

    if dry_run:
        print("--- DRY RUN: would write the following table ---")
        print(new_table)
        return True

    readme_path.write_text(new_content, encoding="utf-8")
    print(f"README module table updated: {readme_path}", file=sys.stderr)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate README module table from config/modules.json",
    )
    parser.add_argument(
        "--readme", default="README.md",
        help="Path to README.md (default: README.md in repo root)",
    )
    parser.add_argument(
        "--modules", default="config/modules.json",
        help="Path to config/modules.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the new table without modifying README.md",
    )
    args = parser.parse_args()

    cfg         = ModulesConfig(args.modules)
    readme_path = Path(args.readme)

    if not readme_path.exists():
        print(f"ERROR: README not found: {readme_path}", file=sys.stderr)
        return 1

    changed = update_readme(readme_path, cfg, dry_run=args.dry_run)
    return 0 if (changed or args.dry_run) else 0


if __name__ == "__main__":
    sys.exit(main())
