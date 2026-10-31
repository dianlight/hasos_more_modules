#!/usr/bin/env python3
"""Tests for the build-planning helpers in scripts/modules_config.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import modules_config as mc  # noqa: E402


def _write_config(tmp: Path, text: str) -> Path:
    path = tmp / "kernel.config"
    path.write_text(text, encoding="utf-8")
    return path


class PlanStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = mc.load_config(REPO_ROOT / "config" / "modules.json")
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def _plan(self, text: str, board: str = "generic_x86_64") -> dict:
        kernel = mc.parse_kernel_config(_write_config(self.tmp, text))
        return mc.plan_build(self.data, board, kernel, version="18.4")

    def test_builtin_module_is_skipped(self) -> None:
        plan = self._plan("CONFIG_NFS_FS=y\n")
        entry = plan["modules"]["nfs"]
        self.assertEqual(entry["status"], mc.STATUS_SKIPPED)
        self.assertIn("built into the HAOS kernel", entry["note"])
        self.assertNotIn("nfs", plan["build"])

    def test_shipped_module_is_skipped(self) -> None:
        plan = self._plan("CONFIG_XFS_FS=m\n")
        entry = plan["modules"]["xfs"]
        self.assertEqual(entry["status"], mc.STATUS_SKIPPED)
        self.assertIn("CONFIG_XFS_FS=m", entry["note"])

    def test_missing_module_is_built(self) -> None:
        plan = self._plan("# CONFIG_XFS_FS is not set\n")
        entry = plan["modules"]["xfs"]
        self.assertEqual(entry["status"], mc.STATUS_BUILD)
        self.assertIn("xfs", plan["build"])
        self.assertIn("xfs", plan["base_build"])

    def test_reshipped_when_config_differs(self) -> None:
        plan = self._plan("CONFIG_NFSD=m\n# CONFIG_NFSD_V4 is not set\nCONFIG_EXPORTFS=m\n")
        entry = plan["modules"]["nfsd"]
        self.assertEqual(entry["status"], mc.STATUS_RESHIPPED)
        self.assertEqual(
            entry["diffs"],
            [{"symbol": "CONFIG_NFSD_V4", "haos": "n", "requested": "y"}],
        )
        self.assertIn("nfsd", plan["build"])
        self.assertIn("nfsd", plan["base_build"])

    def test_builtin_with_config_diff_stays_skipped(self) -> None:
        plan = self._plan("CONFIG_NFSD=y\n# CONFIG_NFSD_V4 is not set\n")
        entry = plan["modules"]["nfsd"]
        self.assertEqual(entry["status"], mc.STATUS_SKIPPED)
        self.assertTrue(entry["diffs"])
        self.assertIn("cannot be applied", entry["note"])

    def test_native_path_skips_out_of_tree_module(self) -> None:
        (self.tmp / "net" / "quic").mkdir(parents=True)
        (self.tmp / "net" / "quic" / "Kconfig").write_text("", encoding="utf-8")
        kernel = mc.parse_kernel_config(_write_config(self.tmp, "# CONFIG_XFS_FS is not set\n"))
        plan = mc.plan_build(self.data, "generic_x86_64", kernel, self.tmp, version="18.4")
        self.assertEqual(plan["modules"]["quic"]["status"], mc.STATUS_SKIPPED)

    def test_excluded_board(self) -> None:
        plan = self._plan("CONFIG_XFS_FS=m\n", board="rpi4_64")
        self.assertEqual(plan["modules"]["zfs"]["status"], mc.STATUS_EXCLUDED)
        self.assertNotIn("zfs", plan["build"])

    def test_all_skipped_flag(self) -> None:
        plan = self._plan(
            "CONFIG_XFS_FS=m\nCONFIG_NFSD=m\nCONFIG_NFSD_V4=y\nCONFIG_EXPORTFS=m\n"
            "CONFIG_NFS_FS=y\nCONFIG_IP_QUIC=m\nCONFIG_ZFS=m\n"
        )
        self.assertTrue(plan["all_skipped"])
        self.assertEqual(plan["base_build"], [])
        self.assertFalse(plan["need_quic"])
        self.assertFalse(plan["need_zfs"])

    def test_needs_for_out_of_tree_modules(self) -> None:
        plan = self._plan("CONFIG_XFS_FS=m\n")
        self.assertTrue(plan["need_quic"])
        self.assertTrue(plan["need_zfs"])
        self.assertIn("quic", plan["patched_build"])
        self.assertIn("zfs", plan["patched_build"])


class ManifestTests(unittest.TestCase):
    def test_manifest_records_statuses_and_failures(self) -> None:
        plan = {
            "board": "generic_x86_64",
            "version": "18.4",
            "modules": {
                "xfs": {"status": mc.STATUS_BUILD, "note": "", "diffs": []},
                "nfsd": {
                    "status": mc.STATUS_RESHIPPED,
                    "note": "",
                    "diffs": [
                        {"symbol": "CONFIG_NFSD_V4", "haos": "n", "requested": "y"}
                    ],
                },
            },
        }
        manifest = mc.write_manifest(
            plan, version="18.4", board="generic_x86_64", zfs_outcome="failure"
        )
        self.assertEqual(manifest["failed"], {"zfs": "generic_x86_64"})
        self.assertEqual(manifest["statuses"]["nfsd"]["status"], mc.STATUS_RESHIPPED)


class ReleaseBodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = mc.load_config(REPO_ROOT / "config" / "modules.json")

    def test_reshipped_cell_notes_config_difference(self) -> None:
        statuses = {
            "nfsd": {
                "generic_x86_64": {
                    "status": mc.STATUS_RESHIPPED,
                    "note": "",
                    "diffs": [
                        {"symbol": "CONFIG_NFSD_V4", "haos": "n", "requested": "y"}
                    ],
                }
            },
            "nfs": {
                "generic_x86_64": {"status": mc.STATUS_SKIPPED, "note": "", "diffs": []}
            },
        }
        body = mc.release_body(
            "18.4", self.data, ["generic_x86_64"], statuses=statuses
        )
        self.assertIn(":recycle:", body)
        self.assertIn(":fast_forward:", body)
        self.assertIn("`CONFIG_NFSD_V4` unset → `y`", body)
        self.assertIn("Skipped – already available in the official distribution", body)

    def test_without_statuses_table_still_renders(self) -> None:
        body = mc.release_body("18.4", self.data, ["generic_aarch64"])
        self.assertIn("`xfs.ko`", body)
        self.assertIn(":white_check_mark:", body)


class AggregateStatusesTests(unittest.TestCase):
    def test_merges_manifests(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        first = tmp / "a.json"
        second = tmp / "b.json"
        first.write_text(
            json.dumps(
                {
                    "board": "generic_x86_64",
                    "statuses": {"xfs": {"status": "build", "note": "", "diffs": []}},
                }
            ),
            encoding="utf-8",
        )
        second.write_text(
            json.dumps(
                {
                    "board": "rpi4_64",
                    "statuses": {"xfs": {"status": "skipped", "note": "", "diffs": []}},
                }
            ),
            encoding="utf-8",
        )
        merged = json.loads(mc.aggregate_statuses([str(first), str(second)]))
        self.assertEqual(merged["xfs"]["generic_x86_64"]["status"], "build")
        self.assertEqual(merged["xfs"]["rpi4_64"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
