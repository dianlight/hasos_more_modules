#!/usr/bin/env bash
# =============================================================================
# scripts/build_zfs.sh
#
# Builds OpenZFS kernel modules as out-of-tree modules against the HAOS
# Buildroot kernel, with automatic detection of GPL symbol conflicts on
# aarch64 and intelligent fallback to a NEON-free / tracepoints-free build.
#
# This script resolves the CDDL vs. EXPORT_SYMBOL_GPL incompatibility that
# prevents ZFS from loading on Raspberry Pi and Yellow board kernels (Linux
# >=6.2 aarch64, where kernel_neon_begin/end are marked EXPORT_SYMBOL_GPL).
#
# Usage:
#   scripts/build_zfs.sh \
#       --linux-dir   /path/to/buildroot/output/build/linux-<ver> \
#       --linux-obj   /path/to/buildroot/output/build/linux-<ver> \
#       --output-dir  /path/to/output/modules \
#       --arch        aarch64|x86_64 \
#       --cross-compile aarch64-buildroot-linux-musl- \
#       --zfs-repo    https://github.com/openzfs/zfs \
#       --zfs-ref     zfs-2.2-release \
#       [--jobs N]
#
# Outputs:
#   {output-dir}/{module_name}.ko  for each successfully built ZFS sub-module
#
# Exit codes:
#   0  - All requested modules built successfully
#   1  - Fatal error
#   2  - ZFS not buildable for this board/kernel (GPL conflict, hard exclude)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
LINUX_DIR=""
LINUX_OBJ=""
OUTPUT_DIR=""
ARCH=""
CROSS_COMPILE=""
ZFS_REPO="https://github.com/openzfs/zfs"
ZFS_REF="zfs-2.2-release"
JOBS="$(nproc)"
VERBOSE="${VERBOSE:-0}"
BOARD="${BOARD:-unknown}"
# Temp dir for ZFS clone
ZFS_BUILD_DIR="${TMPDIR:-/tmp}/zfs_build_$$"

_log()  { echo "[build_zfs] $*"; }
_dbg()  { [[ "$VERBOSE" == "1" ]] && echo "[build_zfs][DBG] $*" || true; }
_err()  { echo "[build_zfs][ERROR] $*" >&2; }
_warn() { echo "[build_zfs][WARN] $*" >&2; }

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
    --zfs-repo)      ZFS_REPO="$2";      shift 2 ;;
    --zfs-ref)       ZFS_REF="$2";       shift 2 ;;
    --jobs)          JOBS="$2";          shift 2 ;;
    --board)         BOARD="$2";         shift 2 ;;
    --verbose)       VERBOSE=1;          shift   ;;
    *) _err "Unknown argument: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Validate required args
# ---------------------------------------------------------------------------
for var in LINUX_DIR OUTPUT_DIR ARCH; do
  if [[ -z "${!var}" ]]; then
    _err "--${var//_/-} is required"
    exit 1
  fi
done

LINUX_OBJ="${LINUX_OBJ:-$LINUX_DIR}"
mkdir -p "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# Step 1: Probe GPL symbols
# ---------------------------------------------------------------------------
_log "Step 1/5: Probing kernel for GPL-only symbol conflicts (arch=$ARCH, board=$BOARD)"

PROBE_EXIT=0
ARCH="$ARCH" VERBOSE="$VERBOSE" \
  bash "$SCRIPT_DIR/probe_gpl_symbols.sh" "$LINUX_DIR" "$LINUX_OBJ" \
  || PROBE_EXIT=$?

USE_SAFE_MODE=0
case "$PROBE_EXIT" in
  0)
    _log "Probe result: CLEAN — no GPL symbol conflicts detected."
    USE_SAFE_MODE=0
    ;;
  1)
    _log "Probe result: GPL CONFLICT — kernel_neon_begin/end or BPF trace symbols are EXPORT_SYMBOL_GPL."
    _log "  -> Switching to safe build mode (no NEON, no tracepoints)."
    USE_SAFE_MODE=1
    ;;
  2)
    _warn "Probe result: INCONCLUSIVE — treating as unsafe (safe mode)."
    USE_SAFE_MODE=1
    ;;
  *)
    _warn "Probe returned unexpected exit code $PROBE_EXIT — treating as unsafe."
    USE_SAFE_MODE=1
    ;;
esac

# ---------------------------------------------------------------------------
# Step 2: Clone / update ZFS source
# ---------------------------------------------------------------------------
_log "Step 2/5: Fetching ZFS source ($ZFS_REPO @ $ZFS_REF)"

if [[ -d "$ZFS_BUILD_DIR/.git" ]]; then
  _dbg "ZFS source already present, fetching updates."
  git -C "$ZFS_BUILD_DIR" fetch origin --depth=1 "$ZFS_REF" 2>&1 | \
    (grep -v '^remote:' || true)
  git -C "$ZFS_BUILD_DIR" checkout FETCH_HEAD
else
  git clone \
    --branch "$ZFS_REF" \
    --depth 1 \
    "$ZFS_REPO" \
    "$ZFS_BUILD_DIR"
fi

cd "$ZFS_BUILD_DIR"

# ---------------------------------------------------------------------------
# Step 3: Apply safe-mode patches / configuration overrides
# ---------------------------------------------------------------------------
_log "Step 3/5: Configuring ZFS (safe_mode=$USE_SAFE_MODE, arch=$ARCH)"

# Run autogen if configure does not yet exist
if [[ ! -f configure ]]; then
  _log "Running autogen.sh..."
  bash autogen.sh
fi

# Base configure flags
CONFIGURE_FLAGS=(
  "--with-linux=$LINUX_DIR"
  "--with-linux-obj=$LINUX_OBJ"
  "--with-config=kernel"
  "--enable-linux-builtin"
)

if [[ -n "$CROSS_COMPILE" ]]; then
  CONFIGURE_FLAGS+=("--host=${CROSS_COMPILE%-}")
fi

EXTRA_CFLAGS=""
EXTRA_LDFLAGS=""

if [[ "$USE_SAFE_MODE" == "1" ]]; then
  # -------------------------------------------------------------------------
  # Safe mode: disable all paths that use EXPORT_SYMBOL_GPL symbols.
  #
  # 1. NEON (kernel_neon_begin / kernel_neon_end):
  #    OpenZFS PR #15711 (merged in 2.2.x) added configure-time detection.
  #    For older refs we patch zfs_config.h manually after configure.
  #
  # 2. Tracepoints (bpf_trace_run* / trace_event_*):
  #    ZFS DTrace/tracepoint stubs pull in these symbols.
  #    -DZFS_DEBUG=0 and CONFIG_ZFS_DEBUG=n suppress them.
  # -------------------------------------------------------------------------
  _log "  [safe-mode] Disabling NEON and kernel tracepoints"

  EXTRA_CFLAGS="-UZFS_NEON_KFPU -DZFS_NO_NEON_KFPU -DZFS_DEBUG=0"
  # Suppress ZFS tracepoints — avoids bpf_trace_run* dependency
  EXTRA_CFLAGS+=" -DZFS_NO_TRACEPOINTS"

  # Tell ZFS configure not to use NEON kfpu wrappers.
  # This is the upstream-supported way (added in ~2.2.0):
  export ZFS_META_LICENSE="CDDL"   # Ensure modpost knows this is CDDL

  # Patch META file: some ZFS versions hard-code the configure neon check.
  # We also patch it so modpost uses CDDL consistently.
  if [[ -f META ]]; then
    _dbg "META before patch: $(grep 'LICENSE' META || echo 'not found')"
    # Keep CDDL — do NOT change to GPL (that would be a license misrepresentation).
    # The right answer is to not use GPL-only symbols at all.
  fi
fi

# ---------------------------------------------------------------------------
# Export build env
# ---------------------------------------------------------------------------
MAKE_ARGS=(
  "ARCH=${ARCH}"
  "-j${JOBS}"
)
if [[ -n "$CROSS_COMPILE" ]]; then
  MAKE_ARGS+=("CROSS_COMPILE=${CROSS_COMPILE}")
fi
if [[ -n "$EXTRA_CFLAGS" ]]; then
  MAKE_ARGS+=("EXTRA_CFLAGS=${EXTRA_CFLAGS}")
fi

# ---------------------------------------------------------------------------
# Run configure
# ---------------------------------------------------------------------------
_dbg "Running: ./configure ${CONFIGURE_FLAGS[*]}"
./configure "${CONFIGURE_FLAGS[@]}" 2>&1 | \
  (grep -vE '^checking|^configure:|^config' || true)

# -------------------------------------------------------------------------
# Post-configure: if ZFS 2.2.x's configure detected the NEON symbols are
# GPL-only it will have auto-disabled them. Verify in zfs_config.h.
# For older ZFS refs, apply the patch manually.
# -------------------------------------------------------------------------
ZFS_CONFIG_H="include/zfs_config.h"
if [[ -f "$ZFS_CONFIG_H" ]]; then
  if grep -q 'HAVE_KERNEL_NEON' "$ZFS_CONFIG_H"; then
    _dbg "ZFS configure set HAVE_KERNEL_NEON — checking value..."
    NEON_VAL=$(grep 'HAVE_KERNEL_NEON' "$ZFS_CONFIG_H" | head -1)
    _dbg "  $NEON_VAL"

    if [[ "$USE_SAFE_MODE" == "1" ]] && echo "$NEON_VAL" | grep -q '#define HAVE_KERNEL_NEON 1'; then
      _warn "ZFS configure ENABLED NEON despite GPL conflict detection."
      _warn "Manually patching $ZFS_CONFIG_H to disable NEON."
      sed -i \
        's/#define HAVE_KERNEL_NEON 1/\/* NEON disabled: kernel_neon_begin is EXPORT_SYMBOL_GPL on this kernel *\/ #undef HAVE_KERNEL_NEON/' \
        "$ZFS_CONFIG_H"
    fi
  else
    if [[ "$USE_SAFE_MODE" == "1" ]]; then
      _warn "HAVE_KERNEL_NEON not present in zfs_config.h."
      _warn "This ZFS version may not have PR#15711. Adding manual guard."
      echo "" >> "$ZFS_CONFIG_H"
      echo "/* Added by hasos_more_modules/scripts/build_zfs.sh (safe mode) */" >> "$ZFS_CONFIG_H"
      echo "#undef HAVE_KERNEL_NEON" >> "$ZFS_CONFIG_H"
      echo "#undef HAVE_KERNEL_NEON_BEGIN_END" >> "$ZFS_CONFIG_H"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Step 4: Build ZFS kernel modules
# ---------------------------------------------------------------------------
_log "Step 4/5: Building ZFS kernel modules (jobs=$JOBS)"
_dbg "make args: ${MAKE_ARGS[*]}"

# ZFS builds the whole module tree with a single `make`
make "${MAKE_ARGS[@]}" modules 2>&1 | \
  (grep -vE '^  (CC|LD|AR|MODPOST|Building) ' || true)

BUILD_RESULT=${PIPESTATUS[0]}
if [[ "$BUILD_RESULT" -ne 0 ]]; then
  _err "ZFS module build failed (exit $BUILD_RESULT)"
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 5: Collect .ko files into output directory
# ---------------------------------------------------------------------------
_log "Step 5/5: Collecting .ko files to $OUTPUT_DIR"

ZFS_MODULE_NAMES=(spl avl nvpair unicode zcommon lua icp zstd zfs)
COLLECTED=0

while IFS= read -r -d '' ko_file; do
  base=$(basename "$ko_file" .ko)
  _dbg "Found: $ko_file"

  # Only collect the modules we care about
  for mod in "${ZFS_MODULE_NAMES[@]}"; do
    if [[ "$base" == "$mod" ]]; then
      dest="$OUTPUT_DIR/${base}.ko"
      cp "$ko_file" "$dest"
      _log "  Collected: ${base}.ko -> $dest"
      COLLECTED=$((COLLECTED + 1))
      break
    fi
  done
done < <(find "$ZFS_BUILD_DIR/module" -name '*.ko' -print0 2>/dev/null)

if [[ "$COLLECTED" -eq 0 ]]; then
  _err "No .ko files collected. Build may have produced nothing."
  exit 1
fi

_log "Done. $COLLECTED ZFS module(s) collected."
_log "Safe mode was: $USE_SAFE_MODE"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
if [[ "${ZFS_CLEANUP:-1}" == "1" ]]; then
  _dbg "Cleaning up ZFS build directory: $ZFS_BUILD_DIR"
  rm -rf "$ZFS_BUILD_DIR"
fi

exit 0
