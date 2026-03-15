#!/usr/bin/env python3
"""
scripts/verify_modules.py
==========================
Verifies that built .ko files have a vermagic string consistent with
the target kernel.  Also checks module license declarations.

A mismatch between the module's vermagic and the running kernel's
uname -r causes 'Invalid module format' when loading.

Usage:
    python3 scripts/verify_modules.py \\
        --modules-dir release_assets \\
        --linux-dir   /path/to/buildroot/output/build/linux-<ver> \\
        --report      release_assets/verify_report.json

Exit codes:
    0  - all modules passed all checks (or only warnings)
    1  - at least one HARD failure (vermagic mismatch, invalid JSON, etc.)
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModuleInfo:
    path:          str
    name:          str
    vermagic:      str   = ""
    license:       str   = ""
    description:   str   = ""
    depends:       str   = ""
    arch:          str   = ""
    parse_error:   str   = ""


@dataclass
class CheckResult:
    module:    str
    check:     str
    status:    str   # "PASS" | "WARN" | "FAIL"
    message:   str


@dataclass
class Report:
    kernel_version:  str
    modules_dir:     str
    results:         list[CheckResult] = field(default_factory=list)
    modules:         list[ModuleInfo]  = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def warnings(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def failures(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def ok(self) -> bool:
        return self.failures == 0


# ---------------------------------------------------------------------------
# .ko parser  (reads .modinfo ELF section without requiring modinfo binary)
# ---------------------------------------------------------------------------

def _parse_ko_modinfo(path: Path) -> ModuleInfo:
    """
    Extract modinfo fields from a .ko ELF file by scanning for the
    null-terminated key=value strings in the .modinfo section.

    Falls back gracefully if the file is not a valid ELF or the section
    is missing.
    """
    info = ModuleInfo(path=str(path), name=path.stem)
    try:
        raw = path.read_bytes()
    except OSError as e:
        info.parse_error = str(e)
        return info

    # Quick ELF magic check
    if raw[:4] != b'\x7fELF':
        info.parse_error = "Not an ELF file"
        return info

    # Scan all printable byte sequences that look like key=value
    # The .modinfo section is a flat array of NUL-terminated strings.
    # Rather than parsing the full ELF structure, we scan the whole file
    # for the known keys — reliable enough for our purposes.
    text = re.sub(rb'[^\x20-\x7e\x00]', b'\x00', raw)
    for chunk in text.split(b'\x00'):
        try:
            s = chunk.decode('ascii', errors='ignore')
        except Exception:
            continue
        if '=' not in s:
            continue
        k, _, v = s.partition('=')
        k = k.strip()
        if k == 'vermagic':
            info.vermagic = v.strip()
        elif k == 'license':
            info.license = v.strip()
        elif k == 'description':
            info.description = v.strip()
        elif k == 'depends':
            info.depends = v.strip()

    return info


# ---------------------------------------------------------------------------
# Kernel version detection
# ---------------------------------------------------------------------------

def _kernel_version_from_linux_dir(linux_dir: Path) -> str:
    """Try multiple methods to extract the kernel version string."""

    # Method 1: include/generated/utsrelease.h
    utsrelease = linux_dir / "include" / "generated" / "utsrelease.h"
    if utsrelease.exists():
        text = utsrelease.read_text(errors='ignore')
        m = re.search(r'UTS_RELEASE\s+"([^"]+)"', text)
        if m:
            return m.group(1)

    # Method 2: Makefile at kernel root (VERSION, PATCHLEVEL, SUBLEVEL)
    makefile = linux_dir / "Makefile"
    if makefile.exists():
        text = makefile.read_text(errors='ignore')
        ver = pat = sub = extra = ""
        for line in text.splitlines():
            if re.match(r'^VERSION\s*=', line):
                ver = line.split('=', 1)[1].strip()
            elif re.match(r'^PATCHLEVEL\s*=', line):
                pat = line.split('=', 1)[1].strip()
            elif re.match(r'^SUBLEVEL\s*=', line):
                sub = line.split('=', 1)[1].strip()
            elif re.match(r'^EXTRAVERSION\s*=', line):
                extra = line.split('=', 1)[1].strip()
        if ver and pat:
            return f"{ver}.{pat}{'.'+sub if sub and sub != '0' else ''}{extra}"

    # Method 3: Module.symvers first line comment (some kernels put version there)
    symvers = linux_dir / "Module.symvers"
    if symvers.exists():
        first = symvers.read_text(errors='ignore').splitlines()
        if first and first[0].startswith('#'):
            m = re.search(r'(\d+\.\d+[\.\d]*\S*)', first[0])
            if m:
                return m.group(1)

    return "unknown"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_vermagic(mod: ModuleInfo, kernel_ver: str) -> CheckResult:
    if mod.parse_error:
        return CheckResult(mod.name, "vermagic", "FAIL",
                           f"Could not parse module: {mod.parse_error}")

    if not mod.vermagic:
        return CheckResult(mod.name, "vermagic", "WARN",
                           "No vermagic found in .modinfo section")

    if kernel_ver == "unknown":
        return CheckResult(mod.name, "vermagic", "WARN",
                           f"Kernel version unknown — cannot verify. "
                           f"Module vermagic: {mod.vermagic!r}")

    # The vermagic starts with the kernel version string followed by space and
    # SMP/PREEMPT/etc flags.  We compare only the version prefix.
    mod_kver = mod.vermagic.split()[0] if mod.vermagic else ""

    if mod_kver == kernel_ver:
        return CheckResult(mod.name, "vermagic", "PASS",
                           f"vermagic matches kernel {kernel_ver!r}")

    # Soft mismatch: might be a LOCALVERSION difference — warn not fail
    # e.g. kernel "6.6.31-v8" vs module "6.6.31-v8-haos"
    if mod_kver.startswith(kernel_ver) or kernel_ver.startswith(mod_kver):
        return CheckResult(mod.name, "vermagic", "WARN",
                           f"vermagic partially matches: module={mod_kver!r} kernel={kernel_ver!r}")

    return CheckResult(mod.name, "vermagic", "FAIL",
                       f"vermagic MISMATCH: module={mod_kver!r} kernel={kernel_ver!r}")


def check_license(mod: ModuleInfo) -> CheckResult:
    KNOWN_LICENSES = {
        "GPL", "GPL v2", "GPL-2.0", "GPL-2.0+",
        "GPL and additional rights",
        "Dual BSD/GPL", "Dual MIT/GPL", "Dual MPL/GPL",
        "CDDL",
    }
    if mod.parse_error:
        return CheckResult(mod.name, "license", "WARN",
                           f"Could not parse module: {mod.parse_error}")

    if not mod.license:
        return CheckResult(mod.name, "license", "WARN",
                           "No license field in .modinfo")

    # GPL modules are always fine; CDDL is expected for ZFS
    if mod.license in KNOWN_LICENSES or mod.license.upper().startswith("GPL"):
        return CheckResult(mod.name, "license", "PASS",
                           f"license={mod.license!r}")

    return CheckResult(mod.name, "license", "WARN",
                       f"Unrecognised license: {mod.license!r}")


def check_not_stripped(mod: ModuleInfo) -> CheckResult:
    """Warn if vermagic is missing (common symptom of an over-stripped module)."""
    if mod.parse_error:
        return CheckResult(mod.name, "stripped", "WARN",
                           f"Parse error: {mod.parse_error}")
    if not mod.vermagic and not mod.license:
        return CheckResult(mod.name, "stripped", "WARN",
                           "Module has no modinfo — may be stripped or corrupted")
    return CheckResult(mod.name, "stripped", "PASS", "modinfo present")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify .ko files against the target kernel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--modules-dir", required=True,
                        help="Directory containing .ko files to verify")
    parser.add_argument("--linux-dir",   required=True,
                        help="Buildroot kernel build directory (for kernel version)")
    parser.add_argument("--report",      default="verify_report.json",
                        help="Path to write the JSON report")
    parser.add_argument("--strict",      action="store_true",
                        help="Exit 1 on warnings too (not just failures)")
    args = parser.parse_args()

    modules_dir = Path(args.modules_dir)
    linux_dir   = Path(args.linux_dir)
    report_path = Path(args.report)

    # Detect kernel version
    kernel_ver = _kernel_version_from_linux_dir(linux_dir)
    print(f"[verify_modules] Kernel version: {kernel_ver!r}")

    ko_files = sorted(modules_dir.glob("*.ko"))
    if not ko_files:
        print("[verify_modules] WARNING: no .ko files found in", modules_dir)
        report = Report(kernel_version=kernel_ver, modules_dir=str(modules_dir))
        report.results.append(CheckResult("(none)", "find", "WARN", "No .ko files found"))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(
            {"kernel_version": report.kernel_version,
             "modules_dir": report.modules_dir,
             "summary": {"passed": 0, "warnings": 1, "failures": 0},
             "results": [asdict(r) for r in report.results],
             "modules": []},
            indent=2,
        ))
        return 0

    report = Report(kernel_version=kernel_ver, modules_dir=str(modules_dir))

    for ko in ko_files:
        mod = _parse_ko_modinfo(ko)
        report.modules.append(mod)

        report.results.append(check_vermagic(mod, kernel_ver))
        report.results.append(check_license(mod))
        report.results.append(check_not_stripped(mod))

        # Print per-module summary
        status_icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}
        for r in report.results[-3:]:
            icon = status_icon.get(r.status, "?")
            print(f"  {icon} [{r.module:20s}] {r.check:12s}: {r.message}")

    # Summary
    print()
    print(f"[verify_modules] Results: "
          f"{report.passed} passed, "
          f"{report.warnings} warnings, "
          f"{report.failures} failures")

    # Write JSON report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(
        {
            "kernel_version": report.kernel_version,
            "modules_dir":    report.modules_dir,
            "summary": {
                "passed":   report.passed,
                "warnings": report.warnings,
                "failures": report.failures,
                "ok":       report.ok,
            },
            "results": [asdict(r) for r in report.results],
            "modules": [
                {
                    "name":        m.name,
                    "vermagic":    m.vermagic,
                    "license":     m.license,
                    "description": m.description,
                    "depends":     m.depends,
                    "parse_error": m.parse_error,
                }
                for m in report.modules
            ],
        },
        indent=2,
    ))
    print(f"[verify_modules] Report written to {report_path}")

    if report.failures > 0:
        return 1
    if args.strict and report.warnings > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
