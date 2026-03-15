"""
scripts/modules_config.py
=========================
Shared library for reading and querying config/modules.json.

All other scripts (check_releases, build_matrix, update_readme, patch_config)
import from here to keep the single-source-of-truth contract.

Usage example:
    from modules_config import ModulesConfig
    cfg = ModulesConfig()
    for mod in cfg.modules_for_board("rpi4_64", arch="aarch64"):
        print(mod.name)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional

# ---------------------------------------------------------------------------
# Default path resolution
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT   = _SCRIPT_DIR.parent
_DEFAULT_MODULES_JSON = _REPO_ROOT / "config" / "modules.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class ExcludeKind(Enum):
    """
    NONE        - module can be built for this board
    HARD        - board can never build this module (hardware/arch impossibility)
    SOFT_NEON   - excluded only if GPL probe detects kernel_neon_begin as GPL-only
    """
    NONE      = "none"
    HARD      = "hard"
    SOFT_NEON = "soft_neon"


@dataclass
class ModuleSource:
    repo:    str
    ref:     str
    kind:    str          # "zfs_module" | "external" | ""
    subdir:  str = ""


@dataclass
class Module:
    name:        str
    description: str
    kconfig:     list[str]
    license:     str
    notes:       str
    source:      Optional[ModuleSource]
    # boards listed in exclude_boards.hard
    hard_excluded_boards:      list[str]
    # boards listed in exclude_boards.soft_neon
    soft_neon_excluded_boards: list[str]
    build_flags_by_arch:       dict

    # -----------------------------------------------------------------------
    @property
    def is_external(self) -> bool:
        """True if this module is built out-of-tree (ZFS, QUIC, …)."""
        return self.source is not None and self.source.kind in ("zfs_module", "external")

    @property
    def is_zfs(self) -> bool:
        return self.source is not None and self.source.kind == "zfs_module"

    def exclude_kind_for(self, board: str) -> ExcludeKind:
        """Return the exclusion kind for the given board name."""
        if board in self.hard_excluded_boards:
            return ExcludeKind.HARD
        if board in self.soft_neon_excluded_boards:
            return ExcludeKind.SOFT_NEON
        return ExcludeKind.NONE

    def is_buildable_for(self, board: str, gpl_safe: bool = True) -> bool:
        """
        Return True if this module can be built for board.

        gpl_safe:
            True  = kernel probe passed (no GPL-only NEON symbols)
            False = probe detected GPL conflict (safe-mode required for ZFS)

        In safe mode, ZFS *can still be built* (with NEON disabled);
        it is not excluded — the workflow records `zfs_safe_mode=true`.
        """
        kind = self.exclude_kind_for(board)
        if kind == ExcludeKind.HARD:
            return False
        # SOFT_NEON: buildable in safe mode even when gpl_safe=False
        return True


@dataclass
class Board:
    name:        str
    arch:        str
    kernel_arch: str
    defconfig:   str
    kernel_tree: str   # "upstream" | "rpi"
    note:        str


@dataclass
class ZfsBuildConfig:
    repo:                  str
    ref:                   str
    configure_base:        list[str]
    configure_aarch64_safe: list[str]
    tracepoints_disable_cflags: str
    modules_order:         list[str]


# ---------------------------------------------------------------------------
# Main config class
# ---------------------------------------------------------------------------

class ModulesConfig:
    """
    Loads and exposes config/modules.json with typed accessors.
    """

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else _DEFAULT_MODULES_JSON
        with open(self._path) as f:
            raw = json.load(f)
        self._raw      = raw
        self._modules  = self._parse_modules(raw.get("modules", []))
        self._boards   = self._parse_boards(raw.get("boards", {}))
        self._zfs      = self._parse_zfs(raw.get("zfs_build", {}))

    # -----------------------------------------------------------------------
    # Parsers
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_modules(raw: list[dict]) -> list[Module]:
        result = []
        for m in raw:
            src_raw = m.get("source")
            source  = None
            if src_raw:
                source = ModuleSource(
                    repo   = src_raw.get("repo", ""),
                    ref    = src_raw.get("ref", ""),
                    kind   = src_raw.get("type", ""),
                    subdir = src_raw.get("subdir", ""),
                )
            exc = m.get("exclude_boards", {})
            result.append(Module(
                name        = m["name"],
                description = m.get("description", ""),
                kconfig     = m.get("kconfig", []),
                license     = m.get("license", "unknown"),
                notes       = m.get("notes", ""),
                source      = source,
                hard_excluded_boards      = exc.get("hard", []),
                soft_neon_excluded_boards = exc.get("soft_neon", []),
                build_flags_by_arch       = m.get("build_flags_by_arch", {}),
            ))
        return result

    @staticmethod
    def _parse_boards(raw: dict) -> dict[str, Board]:
        result = {}
        for name, b in raw.items():
            result[name] = Board(
                name        = name,
                arch        = b.get("arch", ""),
                kernel_arch = b.get("kernel_arch", ""),
                defconfig   = b.get("defconfig", ""),
                kernel_tree = b.get("kernel_tree", "upstream"),
                note        = b.get("_note", ""),
            )
        return result

    @staticmethod
    def _parse_zfs(raw: dict) -> ZfsBuildConfig:
        return ZfsBuildConfig(
            repo                       = raw.get("repo", "https://github.com/openzfs/zfs"),
            ref                        = raw.get("ref", "zfs-2.2-release"),
            configure_base             = raw.get("configure_base", []),
            configure_aarch64_safe     = raw.get("configure_aarch64_safe", []),
            tracepoints_disable_cflags = raw.get("tracepoints_disable_cflags", "-DZFS_NO_TRACEPOINTS"),
            modules_order              = raw.get("modules_order", []),
        )

    # -----------------------------------------------------------------------
    # Accessors
    # -----------------------------------------------------------------------

    @property
    def modules(self) -> list[Module]:
        return list(self._modules)

    @property
    def boards(self) -> dict[str, Board]:
        return dict(self._boards)

    @property
    def zfs(self) -> ZfsBuildConfig:
        return self._zfs

    def board(self, name: str) -> Board:
        if name not in self._boards:
            raise KeyError(f"Unknown board: {name!r}. Known: {list(self._boards)}")
        return self._boards[name]

    def modules_for_board(
        self,
        board_name: str,
        arch: str | None = None,
        *,
        gpl_safe: bool = True,
        include_soft_neon: bool = True,
    ) -> Iterator[tuple[Module, ExcludeKind]]:
        """
        Yield (module, ExcludeKind) for all modules that apply to board_name.

        include_soft_neon:
            True  - include SOFT_NEON excluded modules (they are buildable
                    in safe mode); caller decides how to handle them.
            False - skip SOFT_NEON excluded modules (stricter filter).
        """
        for mod in self._modules:
            kind = mod.exclude_kind_for(board_name)
            if kind == ExcludeKind.HARD:
                continue
            if kind == ExcludeKind.SOFT_NEON and not include_soft_neon:
                continue
            yield mod, kind

    def zfs_modules(self) -> list[Module]:
        """Return all modules built from the ZFS source tree."""
        return [m for m in self._modules if m.is_zfs]

    def in_tree_modules(self) -> list[Module]:
        """Return modules built directly by the Buildroot kernel build."""
        return [m for m in self._modules if not m.is_external]

    def external_modules(self) -> list[Module]:
        """Return out-of-tree modules (ZFS, QUIC, …)."""
        return [m for m in self._modules if m.is_external]

    def boards_with_rpi_kernel(self) -> list[Board]:
        """Return boards that use the Raspberry Pi Foundation kernel tree."""
        return [b for b in self._boards.values() if b.kernel_tree == "rpi"]

    def readme_notes_for(self, mod: Module) -> str:
        """
        Return a human-readable notes string for the README module table.
        Merges soft_neon exclusion info with any explicit notes field.
        """
        parts = []
        if mod.soft_neon_excluded_boards:
            boards_str = ", ".join(f"`{b}`" for b in sorted(mod.soft_neon_excluded_boards))
            parts.append(
                f"⚠️ On {boards_str}: built in **safe mode** "
                f"(no NEON AES acceleration) when `kernel_neon_begin` is "
                f"`EXPORT_SYMBOL_GPL` — detected automatically at build time."
            )
        if mod.notes and not mod.notes.startswith("⚠️"):
            parts.append(mod.notes)
        return " ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# CLI (for quick inspection)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="Inspect modules.json")
    parser.add_argument("--board",  default="", help="Filter for a specific board")
    parser.add_argument("--list-boards", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    cfg = ModulesConfig()

    if args.list_boards:
        for name, b in cfg.boards.items():
            print(f"  {name:20s}  arch={b.arch:8s}  kernel_tree={b.kernel_tree}")
        sys.exit(0)

    if args.board:
        mods = list(cfg.modules_for_board(args.board))
        print(f"Modules for board '{args.board}' ({len(mods)} total):")
        for mod, kind in mods:
            flag = "" if kind == ExcludeKind.NONE else f"  [{kind.value}]"
            print(f"  {mod.name:20s}  license={mod.license:20s}{flag}")
    else:
        for mod in cfg.modules:
            print(f"  {mod.name:20s}  external={mod.is_external}  zfs={mod.is_zfs}  license={mod.license}")
