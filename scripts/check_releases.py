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
        [--board      generic_x86_64 generic_aarch64 ...]

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
from datetime import datetime, timedelta, timezone
from typing import Any

GITHUB_API = "https://api.github.com"
DEFAULT_HAOS_REPO = "home-assistant/operating-system"
DEFAULT_THIS_REPO = "dianlight/hasos_more_modules"

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
        print(
            f"[ERROR] HTTP {exc.code} while fetching {url}: {exc.reason}",
            file=sys.stderr,
        )
        sys.exit(2)
    except urllib.error.URLError as exc:
        print(
            f"[ERROR] Network error while fetching {url}: {exc.reason}", file=sys.stderr
        )
        sys.exit(2)


def fetch_haos_tags(haos_repo: str, token: str | None) -> list[str]:
    """
    Return HAOS release tags to consider for builds, newest first.

    Filtering rules:
    - Exclude releases older than 2 years.
    - Exclude pre-releases that are not newer (by publish date) than the
      latest stable (non-pre-release) release.
    """
    url = f"{GITHUB_API}/repos/{haos_repo}/releases?per_page={PER_PAGE}"
    releases: list[dict] = _get(url, token)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=365 * 2)

    # Determine latest stable release timestamp for prerelease filtering.
    latest_stable_published: datetime | None = None
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        published_at = release.get("published_at")
        if not published_at:
            continue
        try:
            latest_stable_published = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
            break
        except ValueError:
            continue

    filtered_tags: list[str] = []
    for release in releases:
        tag = release.get("tag_name")
        if not tag or release.get("draft"):
            continue

        published_at = release.get("published_at")
        if not published_at:
            continue

        try:
            published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            # Skip malformed release records defensively.
            continue

        # Drop releases that are too old.
        if published_dt < cutoff:
            continue

        # Keep prereleases only if they are newer than the latest stable release.
        if release.get("prerelease") and latest_stable_published:
            if published_dt <= latest_stable_published:
                continue

        filtered_tags.append(tag)

    return filtered_tags


def fetch_compiled_versions(
    this_repo: str,
    boards: list[str] | None,
    token: str | None,
) -> set[str]:
    """
    Return the set of HAOS version tags that have already been compiled.

    If *boards* is provided and non-empty, a version is considered compiled
    only when at least one ``.ko`` asset matching ``_{tag}_{board}.ko`` exists
    for **every** requested board.

    If *boards* is empty or None, any release that contains at least one
    ``.ko`` asset is treated as already compiled.
    """
    url = f"{GITHUB_API}/repos/{this_repo}/releases?per_page={PER_PAGE}"
    releases: list[dict] = _get(url, token)

    compiled: set[str] = set()
    for release in releases:
        tag = release.get("tag_name", "")
        assets: list[dict] = release.get("assets", [])
        asset_names = {a["name"] for a in assets}

        if not boards:
            # No board filter – any .ko file marks the version as done.
            if any(name.endswith(".ko") for name in asset_names):
                compiled.add(tag)
        else:
            # All requested boards must have at least one .ko asset present.
            board_present = {
                board: any(f"_{tag}_{board}.ko" in name for name in asset_names)
                for board in boards
            }
            if all(board_present.values()):
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
        "--board",
        nargs="+",
        default=None,
        metavar="BOARD",
        help=(
            "Board names to check (e.g. generic_x86_64 rpi4_64). "
            "When omitted, any release containing a .ko asset is treated as compiled."
        ),
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

    if args.board:
        print(
            f"[INFO] Checking compiled releases for boards: {', '.join(args.board)}",
            file=sys.stderr,
        )
    else:
        print(
            "[INFO] No boards specified – checking for any compiled .ko assets.",
            file=sys.stderr,
        )

    print(
        f"[INFO] Fetching compiled releases from {args.this_repo} ...",
        file=sys.stderr,
    )
    compiled = fetch_compiled_versions(args.this_repo, args.board, args.token)

    new_tags = [t for t in haos_tags if t not in compiled]

    if not new_tags:
        print(
            "[INFO] All HAOS releases are already compiled. Nothing to do.",
            file=sys.stderr,
        )
        return 1

    print(f"[INFO] {len(new_tags)} new version(s) to compile:", file=sys.stderr)
    for tag in new_tags:
        print(f"  {tag}", file=sys.stderr)
        # Print to stdout for CI capture.
        print(tag)

    return 0


if __name__ == "__main__":
    sys.exit(main())
