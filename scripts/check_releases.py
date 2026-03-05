#!/usr/bin/env python3
"""
check_releases.py – Compare the latest HAOS releases (including pre-releases)
with the versions already published as assets in *this* repository, and print
any version tags that still need to be built.

Usage:
    python3 scripts/check_releases.py \
        --haos-repo  home-assistant/operating-system \
        --this-repo  dianlight/hasos_more_modules \
        [--token      <GITHUB_TOKEN>] \
        [--arch       x86_64 aarch64]

Exit codes:
    0 – at least one new version was found (the list is printed to stdout,
        one tag per line, so the CI can capture it with $() or similar).
    1 – all current HAOS releases are already compiled; nothing to do.
    2 – a fatal error occurred (e.g. API rate limit, network failure).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

GITHUB_API = "https://api.github.com"
DEFAULT_HAOS_REPO = "home-assistant/operating-system"
DEFAULT_THIS_REPO = "dianlight/hasos_more_modules"
DEFAULT_ARCHS = ["x86_64", "aarch64"]

# How many releases to fetch per page (max allowed by GitHub API).
PER_PAGE = 100


def _get(url: str, token: str | None) -> Any:
    """Perform a GET request to the GitHub API and return the parsed JSON."""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"[ERROR] HTTP {exc.code} while fetching {url}: {exc.reason}", file=sys.stderr)
        sys.exit(2)
    except urllib.error.URLError as exc:
        print(f"[ERROR] Network error while fetching {url}: {exc.reason}", file=sys.stderr)
        sys.exit(2)


def fetch_haos_tags(haos_repo: str, token: str | None) -> list[str]:
    """Return all HAOS release tags (including pre-releases), newest first."""
    url = f"{GITHUB_API}/repos/{haos_repo}/releases?per_page={PER_PAGE}"
    releases: list[dict] = _get(url, token)
    # The API returns newest first; keep that order.
    return [r["tag_name"] for r in releases if r.get("tag_name")]


def fetch_compiled_versions(this_repo: str, archs: list[str], token: str | None) -> set[str]:
    """
    Return the set of HAOS version tags that have *all* architectures already
    compiled.  We detect this by looking for release assets whose names match
    the pattern ``*_{version}_{arch}.ko``.
    """
    url = f"{GITHUB_API}/repos/{this_repo}/releases?per_page={PER_PAGE}"
    releases: list[dict] = _get(url, token)

    compiled: set[str] = set()
    for release in releases:
        tag = release.get("tag_name", "")
        assets: list[dict] = release.get("assets", [])
        asset_names = {a["name"] for a in assets}

        # A version is considered compiled when at least one .ko for every
        # requested architecture exists in this release.
        arch_present = {
            arch: any(f"_{tag}_{arch}.ko" in name for name in asset_names)
            for arch in archs
        }
        if all(arch_present.values()):
            compiled.add(tag)

    return compiled


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check which HAOS releases still need kernel modules compiled."
    )
    parser.add_argument(
        "--haos-repo",
        default=os.environ.get("HAOS_REPO", DEFAULT_HAOS_REPO),
        help="Source HAOS repository (default: %(default)s).",
    )
    parser.add_argument(
        "--this-repo",
        default=os.environ.get("THIS_REPO", DEFAULT_THIS_REPO),
        help="This repository where compiled assets are published (default: %(default)s).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub personal access token (or set GITHUB_TOKEN env var).",
    )
    parser.add_argument(
        "--arch",
        nargs="+",
        default=DEFAULT_ARCHS,
        metavar="ARCH",
        help="Architectures to check (default: %(default)s).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print(
        f"[INFO] Fetching HAOS releases from {args.haos_repo} ...",
        file=sys.stderr,
    )
    haos_tags = fetch_haos_tags(args.haos_repo, args.token)
    if not haos_tags:
        print("[WARN] No HAOS releases found.", file=sys.stderr)
        return 1

    print(
        f"[INFO] Fetching compiled releases from {args.this_repo} ...",
        file=sys.stderr,
    )
    compiled = fetch_compiled_versions(args.this_repo, args.arch, args.token)

    new_tags = [t for t in haos_tags if t not in compiled]

    if not new_tags:
        print("[INFO] All HAOS releases are already compiled. Nothing to do.", file=sys.stderr)
        return 1

    print(f"[INFO] {len(new_tags)} new version(s) to compile:", file=sys.stderr)
    for tag in new_tags:
        print(f"  {tag}", file=sys.stderr)
        # Print to stdout for CI capture.
        print(tag)

    return 0


if __name__ == "__main__":
    sys.exit(main())
