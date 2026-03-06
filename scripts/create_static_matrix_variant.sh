#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Create a temporary static-matrix workflow variant for local act testing.

Usage:
  bash scripts/create_static_matrix_variant.sh --version <haos_version> --board <board> [--output <path>]

Examples:
  bash scripts/create_static_matrix_variant.sh --version 17.1 --board generic_aarch64
  bash scripts/create_static_matrix_variant.sh --version 17.1 --board generic_aarch64 --output /tmp/my_variant.yml
EOF
}

VERSION=""
BOARD=""
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      shift 2
      ;;
    --board)
      BOARD="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$VERSION" || -z "$BOARD" ]]; then
  echo "[ERROR] --version and --board are required." >&2
  usage
  exit 1
fi

ROOT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
SRC="$ROOT_DIR/.github/workflows/main_build.yml"

if [[ ! -f "$SRC" ]]; then
  echo "[ERROR] Workflow file not found: $SRC" >&2
  exit 1
fi

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="/tmp/main_build_variant_${VERSION}_${BOARD}.yml"
fi

cp "$SRC" "$OUTPUT"

# Replace the build matrix (version + board) with static arrays.
perl -0777 -i -pe "s/matrix:\n\\s*version:\s*\\$\\{\\{\\s*fromJson\\(needs\\.detect-versions\\.outputs\\.versions\\)\\s*\\}\\}\\n\\s*board:\s*\\$\\{\\{\\s*fromJson\\(needs\\.detect-boards\\.outputs\\.boards\\)\\s*\\}\\}/matrix:\n        version: [\\\"${VERSION}\\\"]\\n        board: [\\\"${BOARD}\\\"]/s" "$OUTPUT"

# Replace the release matrix (version only) with a static array.
perl -0777 -i -pe "s/matrix:\n\\s*version:\s*\\$\\{\\{\\s*fromJson\\(needs\\.detect-versions\\.outputs\\.versions\\)\\s*\\}\\}/matrix:\n        version: [\\\"${VERSION}\\\"]/s" "$OUTPUT"

if ! grep -q "version: \[\"${VERSION}\"\]" "$OUTPUT"; then
  echo "[ERROR] Failed to inject static version matrix." >&2
  exit 1
fi

if ! grep -q "board: \[\"${BOARD}\"\]" "$OUTPUT"; then
  echo "[ERROR] Failed to inject static board matrix." >&2
  exit 1
fi

echo "[OK] Created variant workflow: $OUTPUT"
echo "[OK] Variant: version=${VERSION}, board=${BOARD}"
echo "[INFO] Suggested dry-run command:"
echo "act workflow_dispatch -W $OUTPUT --container-architecture linux/amd64 -P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04 --dryrun"
