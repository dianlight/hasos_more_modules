#!/usr/bin/env bash
# =============================================================================
# scripts/build_quic.sh
#
# Builds the lxin/quic QUIC kernel module as an out-of-tree module against
# the HAOS Buildroot kernel.
#
# QUIC (RFC 9000) kernel module: https://github.com/lxin/quic
# License: GPL-2.0 — no CDDL/GPL symbol conflicts.
#
# Usage:
#   scripts/build_quic.sh \
#       --linux-dir    /path/to/buildroot/output/build/linux-<ver> \
#       --linux-obj    /path/to/buildroot/output/build/linux-<ver> \
#       --output-dir   /path/to/output/modules \
#       --arch         aarch64|x86_64 \
#       --cross-compile aarch64-buildroot-linux-musl- \
#       --quic-repo    https://github.com/lxin/quic \
#       --quic-ref     main \
#       [--jobs N]
#
# Outputs:
#   {output-dir}/quic.ko
#
# Exit codes:
#   0  - Built successfully
#   1  - Fatal error
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
LINUX_DIR=""
LINUX_OBJ=""
OUTPUT_DIR=""
ARCH=""
CROSS_COMPILE=""
QUIC_REPO="https://github.com/lxin/quic"
QUIC_REF="main"
JOBS="$(nproc)"
VERBOSE="${VERBOSE:-0}"
QUIC_BUILD_DIR="${TMPDIR:-/tmp}/quic_build_$$"

_log()  { echo "[build_quic] $*"; }
_dbg()  { [[ "$VERBOSE" == "1" ]] && echo "[build_quic][DBG] $*" || true; }
_err()  { echo "[build_quic][ERROR] $*" >&2; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --linux-dir)     LINUX_DIR="$2";     shift 2 ;;
    --linux-obj)     LINUX_OBJ="$2";     shift 2 ;;
    --output-dir)    OUTPUT_DIR="$2";    shift 2 ;;
    --arch)          ARCH="$2";          shift 2 ;;
    --cross-compile) CROSS_COMPILE="$2"; shift 2 ;;
    --quic-repo)     QUIC_REPO="$2";     shift 2 ;;
    --quic-ref)      QUIC_REF="$2";      shift 2 ;;
    --jobs)          JOBS="$2";          shift 2 ;;
    --verbose)       VERBOSE=1;          shift   ;;
    *) _err "Unknown argument: $1"; exit 1 ;;
  esac
done

for var in LINUX_DIR OUTPUT_DIR ARCH; do
  if [[ -z "${!var}" ]]; then
    _err "--${var//_/-} is required"; exit 1
  fi
done

LINUX_OBJ="${LINUX_OBJ:-$LINUX_DIR}"
mkdir -p "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# Step 1: Clone QUIC source
# ---------------------------------------------------------------------------
_log "Step 1/3: Fetching QUIC source ($QUIC_REPO @ $QUIC_REF)"

if [[ -d "$QUIC_BUILD_DIR/.git" ]]; then
  _dbg "QUIC source already present, updating."
  git -C "$QUIC_BUILD_DIR" fetch origin --depth=1 "$QUIC_REF" 2>&1 | (grep -v '^remote:' || true)
  git -C "$QUIC_BUILD_DIR" checkout FETCH_HEAD
else
  git clone --branch "$QUIC_REF" --depth 1 "$QUIC_REPO" "$QUIC_BUILD_DIR"
fi

# ---------------------------------------------------------------------------
# Step 2: Build the kernel module
# ---------------------------------------------------------------------------
_log "Step 2/3: Building quic.ko (arch=$ARCH, jobs=$JOBS)"

# The lxin/quic module lives in modules/net/quic/
MODULE_DIR="$QUIC_BUILD_DIR/modules/net/quic"
if [[ ! -d "$MODULE_DIR" ]]; then
  # Fallback: some versions put it at the root
  MODULE_DIR="$QUIC_BUILD_DIR"
fi

MAKE_ARGS=(
  "-C" "$LINUX_OBJ"
  "M=$MODULE_DIR"
  "modules"
  "ARCH=${ARCH}"
  "-j${JOBS}"
)

if [[ -n "$CROSS_COMPILE" ]]; then
  MAKE_ARGS+=("CROSS_COMPILE=${CROSS_COMPILE}")
fi

_dbg "Running: make ${MAKE_ARGS[*]}"
make "${MAKE_ARGS[@]}" 2>&1 | (grep -vE '^  (CC|LD|AR) ' || true)

BUILD_EXIT=${PIPESTATUS[0]}
if [[ "$BUILD_EXIT" -ne 0 ]]; then
  _err "quic.ko build failed (exit $BUILD_EXIT)"
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 3: Collect quic.ko
# ---------------------------------------------------------------------------
_log "Step 3/3: Collecting quic.ko to $OUTPUT_DIR"

KO_FILE=$(find "$MODULE_DIR" -name 'quic.ko' | head -1)
if [[ -z "$KO_FILE" ]]; then
  _err "quic.ko not found after build"
  exit 1
fi

cp "$KO_FILE" "$OUTPUT_DIR/quic.ko"
_log "Collected: quic.ko -> $OUTPUT_DIR/quic.ko"

# Cleanup
if [[ "${QUIC_CLEANUP:-1}" == "1" ]]; then
  _dbg "Cleaning up QUIC build directory"
  rm -rf "$QUIC_BUILD_DIR"
fi

exit 0
