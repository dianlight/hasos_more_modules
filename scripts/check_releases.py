#!/usr/bin/env python3
"""
scripts/check_releases.py
==========================
Compares HAOS releases with already-built module assets in this repo
and outputs a list of (version, board) pairs that need building.

Usage:
    python3 scripts/check_releases.py \\
        --haos-repo home-assistant/operating-system \\
        --this-repo dianlight/hasos_more_modules \\
        --output missing_versions.json

    # Force a specific version (bypass HAOS API):
    python3 scripts/check_releases.py ... --force-version 17.2

    # Rebuild everything even if assets already exist:
    python3 scripts/check_releases.py ... --force-rebuild

Environment:
    GITHUB_TOKEN - optional, increases GitHub API rate-limit from 60 to 5000 req/h
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
MIN_HAOS_VER = (13, 0)  # Ignore HAOS releases older than this
MAX_VERSIONS = 20  # Consider only the N most recent HAOS releases
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds

SUPPORTED_ARCH_BY_DEFCONFIG_FLAG: dict[str, str] = {
    "BR2_x86_64=y": "x86_64",
    "BR2_aarch64=y": "aarch64",
}

# A release is considered "complete" if at least this many of the core
# modules are present as assets (tolerates partial ZFS exclusions).
CORE_MODULES = ["xfs", "nfsd", "nfs"]


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


def _gh_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _gh_get(url: str, params: dict | None = None) -> Any:
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        resp = requests.get(url, headers=_gh_headers(), params=params, timeout=30)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - int(time.time()), 1)
            print(f"[check_releases] Rate-limited. Waiting {wait}s…", file=sys.stderr)
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(
        f"GitHub API request failed after {RETRY_ATTEMPTS} attempts: {url}"
    )


def _gh_get_all_pages(url: str, params: dict | None = None) -> list[Any]:
    """Paginate through all results."""
    base_params = dict(params or {})
    base_params.setdefault("per_page", 100)
    results: list[Any] = []
    page = 1
    while True:
        base_params["page"] = page
        data = _gh_get(url, base_params)
        if not data:
            break
        results.extend(data)
        if len(data) < base_params["per_page"]:
            break
        page += 1
    return results


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def _parse_version(tag: str) -> tuple[int, ...] | None:
    """
    Parse a HAOS version tag like '17.1', '13.2', '14.0-rc.1'.
    Returns None for tags that don't match expected patterns.
    """
    # Strip leading 'v' if present
    tag = tag.lstrip("v")
    # Accept X.Y and X.Y.Z but not pre-release tags (rc, beta, dev)
    if re.search(r"(rc|alpha|beta|dev)", tag, re.IGNORECASE):
        return None
    m = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", tag)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def _version_ok(ver: tuple[int, ...]) -> bool:
    return ver[:2] >= MIN_HAOS_VER


# ---------------------------------------------------------------------------
# Fetch HAOS releases
# ---------------------------------------------------------------------------


def fetch_haos_versions(haos_repo: str) -> list[str]:
    """Return stable HAOS version strings, newest first, up to MAX_VERSIONS."""
    url = f"{GITHUB_API}/repos/{haos_repo}/releases"
    data = _gh_get_all_pages(url, {"per_page": 50})

    versions: list[tuple[tuple[int, ...], str]] = []
    for rel in data:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = rel.get("tag_name", "")
        ver = _parse_version(tag)
        if ver and _version_ok(ver):
            versions.append((ver, tag.lstrip("v")))

    # Sort newest first
    versions.sort(key=lambda x: x[0], reverse=True)
    return [v for _, v in versions[:MAX_VERSIONS]]


def _decode_contents_file(content_obj: dict[str, Any]) -> str:
    """Decode file content returned by the GitHub contents API."""
    encoding = content_obj.get("encoding")
    content = content_obj.get("content", "")
    if encoding != "base64":
        raise ValueError("Unexpected GitHub contents encoding")
    return base64.b64decode(content).decode("utf-8", errors="replace")


def _infer_arch_from_defconfig(defconfig_text: str) -> str | None:
    for flag, arch in SUPPORTED_ARCH_BY_DEFCONFIG_FLAG.items():
        if flag in defconfig_text:
            return arch
    return None


def fetch_board_arch_map_from_haos(
    haos_repo: str,
    ref: str,
) -> dict[str, str]:
    """
    Discover board -> arch mapping from HAOS buildroot defconfig files.

    Board names are derived from HAOS *_defconfig names.
    Architecture is inferred from each defconfig's BR2_* flags.
    """
    configs_url = f"{GITHUB_API}/repos/{haos_repo}/contents/buildroot-external/configs"
    config_entries = _gh_get(configs_url, {"ref": ref})
    if not config_entries:
        raise RuntimeError(f"Unable to read HAOS defconfigs from ref '{ref}'")

    board_arch_map: dict[str, str] = {}
    for entry in config_entries:
        defconfig = entry.get("name", "")
        if entry.get("type") != "file" or not defconfig.endswith("_defconfig"):
            continue

        # Keep historical board key for generic x86 image.
        board = (
            "x86_64"
            if defconfig == "generic_x86_64_defconfig"
            else defconfig.removesuffix("_defconfig")
        )
        file_path = f"buildroot-external/configs/{defconfig}"
        file_obj = _gh_get(
            f"{GITHUB_API}/repos/{haos_repo}/contents/{file_path}", {"ref": ref}
        )
        if not file_obj:
            print(
                f"[check_releases] WARN: Defconfig '{defconfig}' not found on ref '{ref}', skipping",
                file=sys.stderr,
            )
            continue

        defconfig_text = _decode_contents_file(file_obj)
        arch = _infer_arch_from_defconfig(defconfig_text)
        if not arch:
            print(
                f"[check_releases] WARN: Could not infer arch for '{board}' from {defconfig}, skipping",
                file=sys.stderr,
            )
            continue
        board_arch_map[board] = arch

    if not board_arch_map:
        raise RuntimeError(f"No supported boards discovered from HAOS ref '{ref}'")

    return board_arch_map


# ---------------------------------------------------------------------------
# Fetch already-built assets in this repo
# ---------------------------------------------------------------------------


def fetch_built_assets(this_repo: str) -> dict[str, set[str]]:
    """
    Return a dict: { version_tag -> set_of_asset_names }.

    Asset names follow the convention: {module}_{version}_{arch}.ko
    e.g. xfs_17.1_x86_64.ko
    """
    url = f"{GITHUB_API}/repos/{this_repo}/releases"
    rels = _gh_get_all_pages(url)
    built: dict[str, set[str]] = {}
    for rel in rels:
        tag = rel.get("tag_name", "").lstrip("v")
        assets = {a["name"] for a in rel.get("assets", [])}
        if tag and assets:
            built[tag] = assets
    return built


# ---------------------------------------------------------------------------
# Determine what's missing
# ---------------------------------------------------------------------------


def missing_combinations(
    haos_versions: list[str],
    built_assets: dict[str, set[str]],
    board_arch_map: dict[str, str],
    force_rebuild: bool = False,
) -> list[dict[str, str]]:
    """
    Return list of { version, board, arch } that need building.
    A combination is missing if ANY core module asset is absent for it.
    """
    missing: list[dict[str, str]] = []

    for version in haos_versions:
        assets = built_assets.get(version, set()) if not force_rebuild else set()

        for board, arch in board_arch_map.items():
            # Check if all core modules are present for this version+board
            needed_assets = {f"{mod}_{version}_{arch}.ko" for mod in CORE_MODULES}
            already_built = needed_assets.issubset(assets)

            if not already_built:
                missing.append(
                    {
                        "version": version,
                        "board": board,
                        "arch": arch,
                    }
                )

    return missing


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect HAOS versions that need new module builds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--haos-repo",
        required=True,
        help="GitHub repo of HAOS, e.g. home-assistant/operating-system",
    )
    parser.add_argument(
        "--this-repo",
        required=True,
        help="GitHub repo of this project, e.g. dianlight/hasos_more_modules",
    )
    parser.add_argument(
        "--output",
        default="missing_versions.json",
        help="Path to write the JSON output (default: missing_versions.json)",
    )
    parser.add_argument(
        "--force-version",
        default="",
        help="Skip HAOS API and use this specific version",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Treat all versions as missing (rebuild everything)",
    )
    parser.add_argument(
        "--max-versions",
        type=int,
        default=MAX_VERSIONS,
        help=f"Max number of recent HAOS releases to consider (default: {MAX_VERSIONS})",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Collect HAOS versions to check
    # -----------------------------------------------------------------------
    if args.force_version:
        print(f"[check_releases] Forced version: {args.force_version}", file=sys.stderr)
        haos_versions = [args.force_version]
    else:
        print(
            f"[check_releases] Fetching HAOS releases from {args.haos_repo}…",
            file=sys.stderr,
        )
        haos_versions = fetch_haos_versions(args.haos_repo)
        print(
            f"[check_releases] Found {len(haos_versions)} stable releases",
            file=sys.stderr,
        )
        if haos_versions:
            print(f"[check_releases] Latest: {haos_versions[0]}", file=sys.stderr)

    if not haos_versions:
        print("[check_releases] No HAOS versions found.", file=sys.stderr)
        result = {"versions": [], "combinations": [], "count": 0}
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        return 0

    # -----------------------------------------------------------------------
    # Discover board/arch map from HAOS source
    # -----------------------------------------------------------------------
    board_ref = args.force_version or haos_versions[0]
    print(
        f"[check_releases] Discovering boards from {args.haos_repo}@{board_ref}…",
        file=sys.stderr,
    )
    board_arch_map = fetch_board_arch_map_from_haos(
        args.haos_repo,
        ref=board_ref,
    )

    print(
        f"[check_releases] Using {len(board_arch_map)} HAOS board(s): "
        f"{', '.join(sorted(board_arch_map))}",
        file=sys.stderr,
    )

    # -----------------------------------------------------------------------
    # Fetch already-built assets
    # -----------------------------------------------------------------------
    if args.force_rebuild:
        print(
            "[check_releases] --force-rebuild: treating all versions as missing",
            file=sys.stderr,
        )
        built_assets: dict[str, set[str]] = {}
    else:
        print(
            f"[check_releases] Fetching built assets from {args.this_repo}…",
            file=sys.stderr,
        )
        built_assets = fetch_built_assets(args.this_repo)
        print(
            f"[check_releases] Found assets for {len(built_assets)} releases",
            file=sys.stderr,
        )

    # -----------------------------------------------------------------------
    # Compute missing
    # -----------------------------------------------------------------------
    missing = missing_combinations(
        haos_versions,
        built_assets,
        board_arch_map,
        force_rebuild=args.force_rebuild,
    )

    # Unique versions with missing builds
    missing_versions = sorted(set(c["version"] for c in missing), reverse=True)

    result = {
        "versions": missing_versions,
        "combinations": missing,
        "count": len(missing),
        "all_haos_versions_checked": haos_versions,
    }

    # -----------------------------------------------------------------------
    # Write output
    # -----------------------------------------------------------------------
    output_path = args.output
    os.makedirs(
        os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
        exist_ok=True,
    )
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(
        f"[check_releases] {len(missing)} missing (version, board) combinations",
        file=sys.stderr,
    )
    for c in missing:
        print(f"  -> {c['version']} / {c['board']} ({c['arch']})", file=sys.stderr)

    print(f"[check_releases] Output written to: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
