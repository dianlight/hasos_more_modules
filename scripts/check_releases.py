#!/usr/bin/env python3
"""
check_releases.py – Compare the latest HAOS releases (including pre-releases)
with the versions already published as assets in *this* repository, and print
any version tags that still need to be built.

A version is flagged as needing a build when:
- It has never been built (no .ko assets matching the tag), OR
- The release was last updated BEFORE the last modification of
  config/modules.json (stale: built before a new module was added).

Usage:
    python3 scripts/check_releases.py \
        --haos-repo  home-assistant/operating-system \
        --this-repo  dianlight/hasos_more_modules \
        [--token      <GITHUB_TOKEN>]

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
MODULES_JSON_PATH = "config/modules.json"

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
            f"[ERROR] Network error while fetching {url}: {exc.reason}",
            file=sys.stderr,
        )
        sys.exit(2)


def fetch_haos_tags(haos_repo: str, token: str | None) -> list[str]:
    """
    Return HAOS release tags to consider for builds, newest first.

    Filtering rules:
    - Exclude draft releases.
    - Exclude releases older than 1 years.
    - Exclude pre-releases that are not newer (by publish date) than the
      latest stable (non-pre-release) release.
    """
    url = f"{GITHUB_API}/repos/{haos_repo}/releases?per_page={PER_PAGE}"
    releases: list[dict] = _get(url, token)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=365 * 1)

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
            continue

        # Drop releases that are too old.
        if published_dt < cutoff:
            continue

        # Keep pre-releases only if they are newer than the latest stable release.
        if release.get("prerelease") and latest_stable_published:
            if published_dt <= latest_stable_published:
                continue

        filtered_tags.append(tag)

    return filtered_tags


def fetch_modules_json_last_modified(
    this_repo: str, token: str | None
) -> datetime | None:
    """
    Return the date of the last commit that touched config/modules.json
    in *this_repo*, or None if it cannot be determined.
    """
    url = f"{GITHUB_API}/repos/{this_repo}/commits?path={MODULES_JSON_PATH}&per_page=1"
    commits: list[dict] = _get(url, token)
    if not commits:
        return None
    try:
        committed_at: str = commits[0]["commit"]["committer"]["date"]
        return datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def fetch_compiled_versions(
    this_repo: str,
    token: str | None,
    modules_json_last_modified: datetime | None,
) -> set[str]:
    """
    Return the set of HAOS version tags that have already been fully compiled.

    A release is considered compiled when BOTH of the following are true:

    1. **Freshness** – the release ``updated_at`` timestamp is strictly newer
       than the last commit date of ``config/modules.json``.  Any release
       built before the modules list was last changed is treated as stale and
       scheduled for a rebuild.
       (Skipped when *modules_json_last_modified* is None.)

    2. **Artifact presence** – the release contains at least one asset whose
       name includes the release tag and ends with ``.ko``, ``.ko.xz``, or
       ``.ko.gz``.
    """
    url = f"{GITHUB_API}/repos/{this_repo}/releases?per_page={PER_PAGE}"
    releases: list[dict] = _get(url, token)

    compiled: set[str] = set()
    for release in releases:
        tag = release.get("tag_name", "")
        if not tag:
            continue

        # ── Rule 1: freshness check ──────────────────────────────────────────
        if modules_json_last_modified is not None:
            updated_at = release.get("updated_at") or release.get("published_at")
            if not updated_at:
                continue
            try:
                updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if updated_dt <= modules_json_last_modified:
                # Built before (or exactly when) modules.json was last changed → stale.
                continue

        # ── Rule 2: at least one matching .ko artifact ───────────────────────
        asset_names: set[str] = {a["name"] for a in release.get("assets", [])}
        has_ko = any(
            tag in name
            and (
                name.endswith(".ko")
                or name.endswith(".ko.xz")
                or name.endswith(".ko.gz")
            )
            for name in asset_names
        )
        if has_ko:
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
        f"[INFO] Fetching last modification date of {MODULES_JSON_PATH} "
        f"from {args.this_repo} ...",
        file=sys.stderr,
    )
    modules_json_mtime = fetch_modules_json_last_modified(args.this_repo, args.token)
    if modules_json_mtime:
        print(
            f"[INFO] {MODULES_JSON_PATH} last modified: {modules_json_mtime.isoformat()}",
            file=sys.stderr,
        )
    else:
        print(
            f"[WARN] Could not determine last modification date of "
            f"{MODULES_JSON_PATH} – freshness check will be skipped.",
            file=sys.stderr,
        )

    print(
        f"[INFO] Fetching compiled releases from {args.this_repo} ...",
        file=sys.stderr,
    )
    compiled = fetch_compiled_versions(args.this_repo, args.token, modules_json_mtime)

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
        print(tag)

    return 0


if __name__ == "__main__":
    sys.exit(main())
