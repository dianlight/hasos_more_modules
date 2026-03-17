#!/usr/bin/env python3
"""Collect built kernel modules and their transitive dependencies.

The configured artifacts in config/modules.json are treated as top-level
requested modules. Their runtime dependencies are resolved from the built
module tree via modinfo and included automatically only when the entire
dependency closure is present.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from modules_config import artifact_names, load_config


@dataclass
class ResolutionResult:
    artifacts: list[str]
    errors: list[str]


def build_module_index(linux_src: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}

    for path in sorted(linux_src.rglob("*.ko")):
        if path.name in index:
            duplicates.setdefault(path.name, [index[path.name]]).append(path)
            continue
        index[path.name] = path

    for artifact, paths in sorted(duplicates.items()):
        chosen = paths[0]
        ignored = ", ".join(str(path) for path in paths[1:])
        print(
            f"[WARN] Multiple matches found for {artifact}; using {chosen} and ignoring {ignored}.",
            file=sys.stderr,
        )

    return index


def read_dependencies(module_path: Path) -> list[str]:
    proc = subprocess.run(
        ["modinfo", "-F", "depends", str(module_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise RuntimeError(f"modinfo failed for {module_path}: {message}")

    raw = proc.stdout.strip()
    if not raw:
        return []

    deps: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        deps.append(name if name.endswith(".ko") else f"{name}.ko")
    return deps


def resolve_artifact(
    artifact: str,
    module_index: dict[str, Path],
) -> ResolutionResult:
    resolved: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    stack = [artifact]

    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)

        module_path = module_index.get(current)
        if module_path is None:
            errors.append(f"{current} not found in build output")
            continue

        resolved.append(current)

        try:
            deps = read_dependencies(module_path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue

        stack.extend(reversed(deps))

    return ResolutionResult(artifacts=resolved, errors=errors)


def copy_artifacts(
    artifacts: set[str],
    module_index: dict[str, Path],
    output_dir: Path,
    version: str,
    board: str,
) -> int:
    copied = 0
    output_dir.mkdir(parents=True, exist_ok=True)

    for artifact in sorted(artifacts):
        source = module_index[artifact]
        destination = output_dir / f"{source.stem}_{version}_{board}.ko"
        shutil.copy2(source, destination)
        print(f"[OK] {destination}")
        copied += 1

    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect kernel module artifacts")
    parser.add_argument("--linux-src", required=True, help="Path to built kernel tree")
    parser.add_argument("--board", required=True, help="Target board")
    parser.add_argument("--version", required=True, help="HAOS version")
    parser.add_argument(
        "--output-dir", required=True, help="Directory for renamed .ko files"
    )
    parser.add_argument(
        "--config",
        default="config/modules.json",
        help="Path to modules.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = load_config(Path(args.config))
    requested_artifacts = artifact_names(data, args.board)
    if not requested_artifacts:
        print(
            "[ERROR] No top-level modules found in config/modules.json", file=sys.stderr
        )
        return 1

    linux_src = Path(args.linux_src)
    output_dir = Path(args.output_dir)
    module_index = build_module_index(linux_src)

    eligible_artifacts: set[str] = set()
    packaged_roots = 0
    for artifact in requested_artifacts:
        resolution = resolve_artifact(artifact, module_index)
        if resolution.errors:
            print(
                f"[WARN] Skipping {artifact}: {'; '.join(resolution.errors)}",
                file=sys.stderr,
            )
            continue

        eligible_artifacts.update(resolution.artifacts)
        packaged_roots += 1
        print(
            f"[INFO] {artifact}: packaging dependency set {', '.join(sorted(resolution.artifacts))}",
            file=sys.stderr,
        )

    if not eligible_artifacts:
        print(
            "[ERROR] No artifacts were eligible for packaging after dependency resolution.",
            file=sys.stderr,
        )
        return 1

    copied = copy_artifacts(
        artifacts=eligible_artifacts,
        module_index=module_index,
        output_dir=output_dir,
        version=args.version,
        board=args.board,
    )
    print(
        f"[INFO] Packaged {copied} unique module(s) from {packaged_roots} requested top-level module(s).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
