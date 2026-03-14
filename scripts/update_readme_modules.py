#!/usr/bin/env python3
"""Update the README module table from config/modules.json."""

from __future__ import annotations

import argparse
from pathlib import Path

from modules_config import load_config, module_rows


START_MARKER = "<!-- modules-table:start -->"
END_MARKER = "<!-- modules-table:end -->"


def render_table(rows: list[str]) -> str:
    lines = [
        START_MARKER,
        "| Module | Description | Notes |",
        "| :-------- | :------------- | :----- |",
        *rows,
        END_MARKER,
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update README module table")
    parser.add_argument("--readme", default="README.md", help="Path to README.md")
    parser.add_argument(
        "--config", default="config/modules.json", help="Path to modules.json"
    )
    args = parser.parse_args()

    readme_path = Path(args.readme)
    config_path = Path(args.config)

    data = load_config(config_path)
    rows = module_rows(data)

    content = readme_path.read_text(encoding="utf-8")
    if START_MARKER not in content or END_MARKER not in content:
        raise ValueError(
            f"README must contain markers '{START_MARKER}' and '{END_MARKER}'"
        )

    before, tail = content.split(START_MARKER, 1)
    _, after = tail.split(END_MARKER, 1)

    updated = before + render_table(rows) + after
    readme_path.write_text(updated, encoding="utf-8")

    print(f"Updated {readme_path} from {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
