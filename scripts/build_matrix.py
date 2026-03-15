#!/usr/bin/env python3
"""
scripts/build_matrix.py
========================
Generates the GitHub Actions strategy matrix JSON from:
  - missing_versions.json  (output of check_releases.py)
    - config/modules.json    (module policy + optional board overrides)

Board list source:
    - Comes from missing_versions.json combinations (already discovered from
        HAOS defconfigs by check_releases.py)
    - build_matrix.py does not maintain its own static board list

The matrix drives the build-modules job: one entry per (version, board) pair.

Usage:
    python3 scripts/build_matrix.py \\
        --missing missing_versions.json \\
        --modules config/modules.json \\
        --output  matrix.json \\
        [--max-pending-versions 1]

    --max-pending-versions N
        Limit the number of distinct HAOS versions included in the matrix per
        CI run. Versions are processed newest-first (from check_releases.py).
        N=0 means no limit (build everything pending).
        N=1 (default) means only the most recent pending version is built per
        run; subsequent runs pick up the next one. This avoids exhausting CI
        minutes when many versions have accumulated.
        Can also be set via the MAX_PENDING_VERSIONS repository variable or
        the workflow_dispatch input of the same name.

Output format (written to --output AND printed to stdout):
    {
      "include": [
        {
          "version":         "17.1",
          "board":           "rpi4_64",
          "arch":            "aarch64",
          "kernel_arch":     "arm64",
          "defconfig":       "rpi4_64_defconfig",
          "cross_compile":   "aarch64-buildroot-linux-musl-",
          "buildroot_arch":  "aarch64",
          "has_zfs":         true,
          "has_soft_neon":   true,
          "zfs_modules":     ["avl", "icp", ...]
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modules_config import ModulesConfig, ExcludeKind  # noqa: E402


# ---------------------------------------------------------------------------
# Cross-compile toolchain mapping
# ---------------------------------------------------------------------------
CROSS_COMPILE_MAP: dict[str, str] = {
    "x86_64": "",
    "aarch64": "aarch64-buildroot-linux-musl-",
}

BUILDROOT_ARCH_MAP: dict[str, str] = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
}

KERNEL_ARCH_MAP: dict[str, str] = {
    "x86_64": "x86",
    "aarch64": "arm64",
}


@dataclass(frozen=True)
class ResolvedBoardConfig:
    arch: str
    kernel_arch: str
    defconfig: str
    kernel_tree: str


def _default_defconfig_for_board(board: str) -> str:
    if board == "x86_64":
        return "generic_x86_64_defconfig"
    return f"{board}_defconfig"


def _resolve_board_config(
    board: str, arch: str, cfg: ModulesConfig
) -> ResolvedBoardConfig:
    """Resolve board settings from modules.json when present, otherwise infer safe defaults."""
    if board in cfg.boards:
        b = cfg.boards[board]
        return ResolvedBoardConfig(
            arch=arch or b.arch,
            kernel_arch=b.kernel_arch,
            defconfig=b.defconfig,
            kernel_tree=b.kernel_tree,
        )

    resolved_arch = arch
    if not resolved_arch:
        raise ValueError(f"Missing architecture for unknown board '{board}'")

    return ResolvedBoardConfig(
        arch=resolved_arch,
        kernel_arch=KERNEL_ARCH_MAP.get(resolved_arch, resolved_arch),
        defconfig=_default_defconfig_for_board(board),
        kernel_tree="upstream",
    )


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def build_matrix(
    missing_path: str | Path,
    modules_path: str | Path,
    max_pending_versions: int = 1,
) -> dict:
    """
    Build and return the GitHub Actions strategy matrix dict.

    max_pending_versions:
        Maximum number of distinct HAOS versions to include in the matrix.
        0 = no limit (build all pending). Default = 1.
    """
    with open(missing_path) as f:
        missing_data = json.load(f)

    cfg = ModulesConfig(modules_path)
    combinations: list[dict] = missing_data.get("combinations", [])
    if not combinations:
        return {"include": []}

    # ------------------------------------------------------------------
    # Apply MAX_PENDING_VERSIONS limit.
    # Versions arrive newest-first from check_releases.py.
    # We collect the first N distinct versions and drop the rest.
    # ------------------------------------------------------------------
    if max_pending_versions > 0:
        allowed_versions: list[str] = []
        for combo in combinations:
            v = combo.get("version", "")
            if v and v not in allowed_versions:
                allowed_versions.append(v)
                if len(allowed_versions) >= max_pending_versions:
                    break
        original_count = len(combinations)
        combinations = [c for c in combinations if c.get("version") in allowed_versions]
        skipped = original_count - len(combinations)
        print(
            f"[build_matrix] MAX_PENDING_VERSIONS={max_pending_versions}: "
            f"building versions {allowed_versions}"
            + (
                f", skipping {skipped} combinations from older versions"
                if skipped
                else ""
            ),
            file=sys.stderr,
        )
    else:
        print(
            f"[build_matrix] MAX_PENDING_VERSIONS=0 (unlimited): "
            f"{len(combinations)} pending combinations",
            file=sys.stderr,
        )

    # ------------------------------------------------------------------
    # Build matrix entries
    # ------------------------------------------------------------------
    include: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for combo in combinations:
        version = combo["version"]
        board = combo["board"]
        arch = combo.get("arch", "")

        key = (version, board)
        if key in seen:
            continue
        seen.add(key)

        board_cfg = _resolve_board_config(board, arch, cfg)

        # Collect ZFS modules for this board
        zfs_names: list[str] = []
        has_soft_neon = False

        for mod, kind in cfg.modules_for_board(
            board, arch=arch, include_soft_neon=True
        ):
            if not mod.is_zfs:
                continue
            if kind == ExcludeKind.SOFT_NEON:
                has_soft_neon = True
            zfs_names.append(mod.name)

        # Preserve ZFS sub-module load order
        order = cfg.zfs.modules_order
        zfs_names_ordered = [n for n in order if n in zfs_names] + [
            n for n in zfs_names if n not in order
        ]

        has_zfs = bool(zfs_names_ordered)

        entry = {
            "version": version,
            "board": board,
            "arch": board_cfg.arch,
            "kernel_arch": board_cfg.kernel_arch,
            "defconfig": board_cfg.defconfig,
            "cross_compile": CROSS_COMPILE_MAP.get(board_cfg.arch, ""),
            "buildroot_arch": BUILDROOT_ARCH_MAP.get(board_cfg.arch, board_cfg.arch),
            "has_zfs": has_zfs,
            "has_soft_neon": has_soft_neon,
            "zfs_modules": zfs_names_ordered,
            "kernel_tree": board_cfg.kernel_tree,
        }
        include.append(entry)
        print(
            f"[build_matrix] {version} / {board:12s}  "
            f"defconfig={board_cfg.defconfig:30s}  "
            f"arch={board_cfg.arch:8s}  "
            f"has_zfs={has_zfs}  has_soft_neon={has_soft_neon}",
            file=sys.stderr,
        )

    matrix = {"include": include}
    print(f"[build_matrix] Matrix: {len(include)} entries total", file=sys.stderr)
    return matrix


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate GitHub Actions matrix from missing releases",
    )
    parser.add_argument(
        "--missing",
        required=True,
        help="Path to missing_versions.json (output of check_releases.py)",
    )
    parser.add_argument(
        "--modules", default="config/modules.json", help="Path to config/modules.json"
    )
    parser.add_argument(
        "--output",
        default="matrix.json",
        help="Path to write matrix JSON (default: matrix.json)",
    )
    parser.add_argument(
        "--max-pending-versions",
        type=int,
        default=1,
        dest="max_pending_versions",
        help=(
            "Max number of distinct HAOS versions to build per CI run "
            "(0 = no limit, default: 1). "
            "Set via workflow_dispatch input or MAX_PENDING_VERSIONS repo variable."
        ),
    )
    args = parser.parse_args()

    matrix = build_matrix(
        args.missing,
        args.modules,
        max_pending_versions=args.max_pending_versions,
    )

    os.makedirs(
        os.path.dirname(args.output) if os.path.dirname(args.output) else ".",
        exist_ok=True,
    )
    with open(args.output, "w") as f:
        json.dump(matrix, f, indent=2)

    # Print compact JSON to stdout for GitHub Actions capture
    print(json.dumps(matrix))
    return 0


if __name__ == "__main__":
    sys.exit(main())
