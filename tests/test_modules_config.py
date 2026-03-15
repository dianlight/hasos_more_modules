"""
tests/test_modules_config.py
============================
Test suite for hasos_more_modules Python scripts.

Run with:
    python3 -m pytest tests/ -v
    # or
    python3 -m pytest tests/test_modules_config.py -v
"""

# pyright: reportMissingImports=false

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from modules_config import ExcludeKind, ModulesConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES_JSON = REPO_ROOT / "config" / "modules.json"


@pytest.fixture(scope="module")
def cfg() -> ModulesConfig:
    """Load the real modules.json from the repo."""
    return ModulesConfig(MODULES_JSON)


@pytest.fixture
def minimal_json(tmp_path) -> Path:
    """Write a minimal modules.json for isolated tests."""
    data = {
        "modules": [
            {
                "name": "xfs",
                "description": "XFS filesystem",
                "kconfig": ["CONFIG_XFS_FS"],
                "license": "GPL-2.0",
            },
            {
                "name": "zfs",
                "description": "ZFS filesystem",
                "kconfig": [],
                "license": "CDDL-1.0",
                "source": {
                    "repo": "https://github.com/openzfs/zfs",
                    "ref": "zfs-2.2-release",
                    "type": "zfs_module",
                    "subdir": "module/zfs",
                },
                "exclude_boards": {
                    "hard": ["nonexistent_board"],
                    "soft_neon": ["rpi4_64", "yellow"],
                },
            },
        ],
        "boards": {
            "x86_64": {
                "arch": "x86_64",
                "kernel_arch": "x86",
                "defconfig": "pc_x86_64_efi_defconfig",
                "kernel_tree": "upstream",
            },
            "rpi4_64": {
                "arch": "aarch64",
                "kernel_arch": "arm64",
                "defconfig": "rpi4_defconfig",
                "kernel_tree": "rpi",
            },
            "yellow": {
                "arch": "aarch64",
                "kernel_arch": "arm64",
                "defconfig": "yellow_defconfig",
                "kernel_tree": "rpi",
            },
        },
        "zfs_build": {
            "repo": "https://github.com/openzfs/zfs",
            "ref": "zfs-2.2-release",
            "configure_base": ["--with-config=kernel"],
            "configure_aarch64_safe": ["--with-config=kernel", "--without-neon"],
            "tracepoints_disable_cflags": "-DZFS_NO_TRACEPOINTS",
            "modules_order": ["zfs"],
        },
    }
    p = tmp_path / "modules.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# Tests: ModulesConfig.modules
# ---------------------------------------------------------------------------


class TestModules:
    def test_modules_loads(self, cfg):
        assert len(cfg.modules) > 0

    def test_xfs_present(self, cfg):
        names = [m.name for m in cfg.modules]
        assert "xfs" in names

    def test_zfs_present(self, cfg):
        names = [m.name for m in cfg.modules]
        assert "zfs" in names

    def test_nfs_present(self, cfg):
        names = [m.name for m in cfg.modules]
        assert "nfs" in names

    def test_xfs_is_not_external(self, cfg):
        xfs = next(m for m in cfg.modules if m.name == "xfs")
        assert not xfs.is_external
        assert not xfs.is_zfs

    def test_zfs_is_external_and_zfs(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.is_external
        assert zfs.is_zfs

    def test_all_zfs_modules_are_zfs(self, cfg):
        zfs_names = {"avl", "icp", "lua", "nvpair", "unicode", "zcommon", "zstd", "zfs"}
        for mod in cfg.modules:
            if mod.name in zfs_names:
                assert mod.is_zfs, f"{mod.name} should be is_zfs=True"

    def test_zfs_modules_have_cddl_license(self, cfg):
        for mod in cfg.zfs_modules():
            assert "CDDL" in mod.license, f"{mod.name} should have CDDL license"

    def test_gpl_modules_have_gpl_license(self, cfg):
        gpl_names = {"xfs", "nfsd", "nfs", "quic"}
        for mod in cfg.modules:
            if mod.name in gpl_names:
                assert "GPL" in mod.license, f"{mod.name} should have GPL license"

    def test_kconfig_symbols_present(self, cfg):
        xfs = next(m for m in cfg.modules if m.name == "xfs")
        assert "CONFIG_XFS_FS" in xfs.kconfig

    def test_zfs_has_no_kconfig(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.kconfig == []


# ---------------------------------------------------------------------------
# Tests: Board exclusions
# ---------------------------------------------------------------------------


class TestExclusions:
    def test_xfs_not_excluded_for_rpi4(self, cfg):
        xfs = next(m for m in cfg.modules if m.name == "xfs")
        assert xfs.exclude_kind_for("rpi4_64") == ExcludeKind.NONE

    def test_zfs_soft_neon_excluded_for_rpi4(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.exclude_kind_for("rpi4_64") == ExcludeKind.SOFT_NEON

    def test_zfs_soft_neon_excluded_for_yellow(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.exclude_kind_for("yellow") == ExcludeKind.SOFT_NEON

    def test_zfs_soft_neon_excluded_for_rpi3(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.exclude_kind_for("rpi3_64") == ExcludeKind.SOFT_NEON

    def test_zfs_not_excluded_for_x86(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.exclude_kind_for("x86_64") == ExcludeKind.NONE

    def test_zfs_not_excluded_for_odroid(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.exclude_kind_for("odroid_n2") == ExcludeKind.NONE

    def test_is_buildable_ignores_soft_neon(self, cfg):
        """ZFS is buildable even on RPi (in safe mode)."""
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        assert zfs.is_buildable_for("rpi4_64", gpl_safe=False) is True
        assert zfs.is_buildable_for("rpi4_64", gpl_safe=True) is True

    def test_hard_excluded_is_not_buildable(self, minimal_json):
        cfg2 = ModulesConfig(minimal_json)
        zfs = next(m for m in cfg2.modules if m.name == "zfs")
        assert zfs.is_buildable_for("nonexistent_board") is False

    def test_all_four_rpi_boards_soft_neon(self, cfg):
        """All 4 RPi/Yellow boards should be soft_neon excluded for ZFS modules."""
        rpi_boards = ["rpi3_64", "rpi4_64", "rpi5_64", "yellow"]
        for mod in cfg.zfs_modules():
            for board in rpi_boards:
                kind = mod.exclude_kind_for(board)
                assert (
                    kind == ExcludeKind.SOFT_NEON
                ), f"{mod.name} should be SOFT_NEON on {board}, got {kind}"


# ---------------------------------------------------------------------------
# Tests: modules_for_board iterator
# ---------------------------------------------------------------------------


class TestModulesForBoard:
    def test_x86_gets_all_modules(self, cfg):
        mods = {m.name: k for m, k in cfg.modules_for_board("x86_64")}
        assert "xfs" in mods
        assert "zfs" in mods
        assert all(k == ExcludeKind.NONE for k in mods.values())

    def test_rpi4_gets_in_tree_modules(self, cfg):
        mods = {m.name: k for m, k in cfg.modules_for_board("rpi4_64")}
        assert ExcludeKind.NONE == mods["xfs"]
        assert ExcludeKind.NONE == mods["nfsd"]

    def test_rpi4_gets_zfs_with_soft_neon_kind(self, cfg):
        mods = {m.name: k for m, k in cfg.modules_for_board("rpi4_64")}
        assert ExcludeKind.SOFT_NEON == mods["zfs"]

    def test_rpi4_excludes_soft_neon_when_flag_set(self, cfg):
        mods = {
            m.name: k
            for m, k in cfg.modules_for_board("rpi4_64", include_soft_neon=False)
        }
        assert "zfs" not in mods
        assert "xfs" in mods

    def test_hard_excluded_board_never_gets_module(self, minimal_json):
        cfg2 = ModulesConfig(minimal_json)
        mods = {m.name: k for m, k in cfg2.modules_for_board("nonexistent_board")}
        # zfs has nonexistent_board in hard exclusions
        assert "zfs" not in mods


# ---------------------------------------------------------------------------
# Tests: boards
# ---------------------------------------------------------------------------


class TestBoards:
    def test_all_expected_boards_present(self, cfg):
        expected = {"x86_64", "rpi3_64", "rpi4_64", "rpi5_64", "yellow"}
        assert expected.issubset(set(cfg.boards.keys()))

    def test_rpi_boards_have_rpi_kernel_tree(self, cfg):
        for b in cfg.boards_with_rpi_kernel():
            assert b.kernel_tree == "rpi"
            assert b.name in {"rpi3_64", "rpi4_64", "rpi5_64", "yellow"}

    def test_x86_has_upstream_kernel_tree(self, cfg):
        assert cfg.board("x86_64").kernel_tree == "upstream"

    def test_board_raises_on_unknown(self, cfg):
        with pytest.raises(KeyError):
            cfg.board("nonexistent_board_xyz")

    def test_four_rpi_boards_in_rpi_tree(self, cfg):
        rpi = {b.name for b in cfg.boards_with_rpi_kernel()}
        assert rpi == {"rpi3_64", "rpi4_64", "rpi5_64", "yellow"}


# ---------------------------------------------------------------------------
# Tests: ZFS build config
# ---------------------------------------------------------------------------


class TestZfsBuild:
    def test_zfs_repo_is_openzfs(self, cfg):
        assert "openzfs/zfs" in cfg.zfs.repo

    def test_zfs_ref_not_empty(self, cfg):
        assert cfg.zfs.ref

    def test_configure_base_not_empty(self, cfg):
        assert len(cfg.zfs.configure_base) > 0

    def test_configure_aarch64_safe_has_without_neon(self, cfg):
        assert any("neon" in flag.lower() for flag in cfg.zfs.configure_aarch64_safe)

    def test_modules_order_has_zfs_last(self, cfg):
        order = cfg.zfs.modules_order
        assert order[-1] == "zfs", f"zfs should be last in order, got {order}"

    def test_modules_order_has_avl_before_zfs(self, cfg):
        order = cfg.zfs.modules_order
        assert order.index("avl") < order.index("zfs")

    def test_tracepoints_cflags_present(self, cfg):
        assert "TRACEPOINTS" in cfg.zfs.tracepoints_disable_cflags.upper()


# ---------------------------------------------------------------------------
# Tests: README notes generation
# ---------------------------------------------------------------------------


class TestReadmeNotes:
    def test_zfs_notes_mention_safe_mode(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        notes = cfg.readme_notes_for(zfs)
        assert "safe mode" in notes.lower()

    def test_xfs_notes_empty(self, cfg):
        xfs = next(m for m in cfg.modules if m.name == "xfs")
        notes = cfg.readme_notes_for(xfs)
        assert notes == ""

    def test_notes_mention_neon(self, cfg):
        zfs = next(m for m in cfg.modules if m.name == "zfs")
        notes = cfg.readme_notes_for(zfs)
        assert "neon" in notes.lower() or "NEON" in notes


# ---------------------------------------------------------------------------
# Tests: zfs_modules() and in_tree_modules()
# ---------------------------------------------------------------------------


class TestModuleCategories:
    def test_in_tree_modules_have_kconfig(self, cfg):
        for mod in cfg.in_tree_modules():
            assert len(mod.kconfig) > 0, f"{mod.name} should have kconfig symbols"

    def test_zfs_modules_have_source(self, cfg):
        for mod in cfg.zfs_modules():
            assert mod.source is not None
            assert mod.source.repo

    def test_quic_is_external_but_not_zfs(self, cfg):
        quic = next((m for m in cfg.modules if m.name == "quic"), None)
        if quic:
            assert quic.is_external
            assert not quic.is_zfs

    def test_in_tree_modules_not_in_zfs_modules(self, cfg):
        zfs_names = {m.name for m in cfg.zfs_modules()}
        for mod in cfg.in_tree_modules():
            assert mod.name not in zfs_names


# ---------------------------------------------------------------------------
# Tests: build_matrix.py integration
# ---------------------------------------------------------------------------


class TestBuildMatrix:
    def test_matrix_generated_correctly(self, tmp_path, minimal_json):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from build_matrix import build_matrix

        missing = {
            "versions": ["17.1"],
            "combinations": [
                {"version": "17.1", "board": "x86_64", "arch": "x86_64"},
                {"version": "17.1", "board": "rpi4_64", "arch": "aarch64"},
                {"version": "17.1", "board": "yellow", "arch": "aarch64"},
            ],
            "count": 3,
        }
        missing_file = tmp_path / "missing.json"
        missing_file.write_text(json.dumps(missing))

        matrix = build_matrix(str(missing_file), str(minimal_json))
        include = matrix["include"]

        assert len(include) == 3

        x86 = next(e for e in include if e["board"] == "x86_64")
        assert x86["has_zfs"] is True
        assert x86["has_soft_neon"] is False
        assert x86["kernel_tree"] == "upstream"

        rpi4 = next(e for e in include if e["board"] == "rpi4_64")
        assert rpi4["has_zfs"] is True
        assert rpi4["has_soft_neon"] is True
        assert rpi4["kernel_tree"] == "rpi"
        assert "zfs" in rpi4["zfs_modules"]

    def test_empty_missing_gives_empty_matrix(self, tmp_path, minimal_json):
        from build_matrix import build_matrix

        missing = {"versions": [], "combinations": [], "count": 0}
        missing_file = tmp_path / "missing.json"
        missing_file.write_text(json.dumps(missing))

        matrix = build_matrix(str(missing_file), str(minimal_json))
        assert matrix["include"] == []

    def test_unknown_board_uses_inferred_defaults(self, tmp_path, minimal_json):
        from build_matrix import build_matrix

        missing = {
            "versions": ["17.1"],
            "combinations": [
                {"version": "17.1", "board": "unknown_board_xyz", "arch": "aarch64"},
            ],
            "count": 1,
        }
        missing_file = tmp_path / "missing.json"
        missing_file.write_text(json.dumps(missing))

        matrix = build_matrix(str(missing_file), str(minimal_json))
        assert len(matrix["include"]) == 1
        entry = matrix["include"][0]
        assert entry["board"] == "unknown_board_xyz"
        assert entry["arch"] == "aarch64"
        assert entry["kernel_arch"] == "arm64"
        assert entry["defconfig"] == "unknown_board_xyz_defconfig"
        assert entry["kernel_tree"] == "upstream"


# ---------------------------------------------------------------------------
# Tests: update_readme_modules.py
# ---------------------------------------------------------------------------


class TestUpdateReadme:
    def test_generate_table_has_all_modules(self, cfg):
        from update_readme_modules import generate_table

        table = generate_table(cfg)
        for mod in cfg.modules:
            assert f"`{mod.name}.ko`" in table

    def test_generate_table_has_board_headers(self, cfg):
        from update_readme_modules import generate_table

        table = generate_table(cfg)
        assert "x86_64" in table
        assert "rpi4" in table

    def test_generate_table_has_legend(self, cfg):
        from update_readme_modules import generate_table

        table = generate_table(cfg)
        assert "✅" in table
        assert "⚠️" in table

    def test_update_readme_modifies_file(self, cfg, tmp_path):
        from update_readme_modules import TABLE_END, TABLE_START, update_readme

        readme = tmp_path / "README.md"
        readme.write_text(
            f"# Test\n\n{TABLE_START}\nold content\n{TABLE_END}\n\nEnd.\n"
        )
        changed = update_readme(readme, cfg, dry_run=False)
        assert changed is True
        content = readme.read_text()
        assert "old content" not in content
        assert "xfs.ko" in content

    def test_update_readme_no_change_if_up_to_date(self, cfg, tmp_path):
        """Running update twice should report no change on the second run."""
        from update_readme_modules import (
            TABLE_END,
            TABLE_START,
            generate_table,
            update_readme,
        )

        table = generate_table(cfg)
        readme = tmp_path / "README.md"
        readme.write_text(f"# Test\n\n{TABLE_START}\n{table}\n{TABLE_END}\n")
        changed = update_readme(readme, cfg, dry_run=False)
        assert changed is False

    def test_update_readme_fails_without_sentinels(self, cfg, tmp_path):
        from update_readme_modules import update_readme

        readme = tmp_path / "README.md"
        readme.write_text("# README without sentinels\n")
        changed = update_readme(readme, cfg, dry_run=False)
        assert changed is False  # returns False on error


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        check=False,
    )
