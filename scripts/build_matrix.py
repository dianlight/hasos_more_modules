#!/usr/bin/env python3
"""
scripts/build_matrix.py
========================
Generates the GitHub Actions strategy matrix JSON from:
  - missing_versions.json  (output of check_releases.py)
  - config/modules.json    (board definitions + module list)

The matrix drives the build-modules job: one entry per (version, board) pair.

Usage:
    python3 scripts/build_matrix.py \\
        --missing missing_versions.json \\
        --modules config/modules.json \\
        --output  matrix.json

Output format (written to --output AND printed to stdout):
    {
      "include": [
        {
          "version":         "17.1",
          "board":           "rpi4_64",
          "arch":            "aarch64",
          "kernel_arch":     "arm64",
          "defconfig":       "rpi4_defconfig",
          "cross_compile":   "aarch64-buildroot-linux-musl-",
          "buildroot_arch":  "aarch64",
          "has_zfs":         true,
          "has_soft_neon":   true,
          "zfs_modules":     ["avl", "icp", "lua", "nvpair", "unicode", "zcommon", "zstd", "zfs"]
        },
        ...
      ]
    }

Fields:
    has_zfs         true if any ZFS module is configured AND not hard-excluded for this board
    has_soft_neon   true if any ZFS module is soft_neon excluded for this board
                    (build_zfs.sh will run probe_gpl_symbols.sh to decide safe mode)
    zfs_modules     ordered list of ZFS module names to build for this board
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add scripts/ to path so we can import modules_config
sys.path.insert(0, str(Path(__file__).resolve().parent))
from modules_config import ModulesConfig, ExcludeKind


# ---------------------------------------------------------------------------
# Cross-compile toolchain mapping
# Key: arch   Value: CROSS_COMPILE prefix used in Buildroot
# ---------------------------------------------------------------------------
CROSS_COMPILE_MAP: dict[str, str] = {
    "x86_64":  "",                                    # native build
    "aarch64": "aarch64-buildroot-linux-musl-",
}

# Buildroot arch string (used as BR2_ARCH)
BUILDROOT_ARCH_MAP: dict[str, str] = {
    "x86_64":  "x86_64",
    "aarch64": "aarch64",
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_matrix(
    missing_path: str | Path,
    modules_path: str | Path,
) -> dict:
    """
    Build and return the GitHub Actions matrix dict.
    """
    with open(missing_path) as f:
        missing_data = json.load(f)

    cfg = ModulesConfig(modules_path)
    boards = cfg.boards

    combinations = missing_data.get("combinations", [])
    if not combinations:
        return {"include": []}

    include: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for combo in combinations:
        version = combo["version"]
        board   = combo["board"]
        arch    = combo.get("arch", "")

        key = (version, board)
        if key in seen:
            continue
        seen.add(key)

        # Resolve board config
        if board not in boards:
            print(f"[build_matrix] WARN: unknown board '{board}', skipping", file=sys.stderr)
            continue

        board_cfg = boards[board]

        # Collect modules for this board (include soft_neon ones — build_zfs.sh handles them)
        zfs_names:      list[str] = []
        has_soft_neon   = False

        for mod, kind in cfg.modules_for_board(board, arch=arch, include_soft_neon=True):
            if not mod.is_zfs:
                continue
            if kind == ExcludeKind.SOFT_NEON:
                has_soft_neon = True
            zfs_names.append(mod.name)

        # Preserve load order from zfs_build.modules_order
        order = cfg.zfs.modules_order
        zfs_names_ordered = [n for n in order if n in zfs_names] + \
                            [n for n in zfs_names if n not in order]

        has_zfs = bool(zfs_names_ordered)

        entry = {
            "version":        version,
            "board":          board,
            "arch":           arch or board_cfg.arch,
            "kernel_arch":    board_cfg.kernel_arch,
            "defconfig":      board_cfg.defconfig,
            "cross_compile":  CROSS_COMPILE_MAP.get(board_cfg.arch, ""),
            "buildroot_arch": BUILDROOT_ARCH_MAP.get(board_cfg.arch, board_cfg.arch),
            "has_zfs":        has_zfs,
            "has_soft_neon":  has_soft_neon,
            "zfs_modules":    zfs_names_ordered,
            "kernel_tree":    board_cfg.kernel_tree,
        }
        include.append(entry)
        print(
            f"[build_matrix] {version} / {board:12s}  "
            f"arch={board_cfg.arch:8s}  "
            f"has_zfs={has_zfs}  "
            f"has_soft_neon={has_soft_neon}",
            file=sys.stderr,
        )

    matrix = {"include": include}
    print(f"[build_matrix] Matrix has {len(include)} entries", file=sys.stderr)
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate GitHub Actions matrix from missing releases",
    )
    parser.add_argument("--missing", required=True,
                        help="Path to missing_versions.json (output of check_releases.py)")
    parser.add_argument("--modules", default="config/modules.json",
                        help="Path to config/modules.json")
    parser.add_argument("--output",  default="matrix.json",
                        help="Path to write matrix JSON (default: matrix.json)")
    args = parser.parse_args()

    matrix = build_matrix(args.missing, args.modules)

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(matrix, f, indent=2)

    # Also print to stdout (for GitHub Actions `echo "matrix=$(cat matrix.json)"`)
    print(json.dumps(matrix))
    return 0


if __name__ == "__main__":
    sys.exit(main())
