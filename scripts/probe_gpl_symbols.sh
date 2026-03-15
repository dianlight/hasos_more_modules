#!/usr/bin/env bash
# =============================================================================
# scripts/probe_gpl_symbols.sh
#
# Probes the target kernel build directory to determine whether specific
# symbols are exported as EXPORT_SYMBOL_GPL (i.e., inaccessible to CDDL
# modules).  Exits 0 if ZFS can safely use NEON on this kernel, exits 1
# if the symbols are GPL-only (ZFS must build without NEON).
#
# Usage:
#   scripts/probe_gpl_symbols.sh <LINUX_DIR> <LINUX_OBJ>
#
# Environment:
#   ARCH           - Target architecture (e.g. aarch64, x86_64)
#   VERBOSE        - Set to 1 for extra output
#
# Exit codes:
#   0 - Safe: symbols are NOT GPL-only (or arch is not aarch64/arm)
#   1 - Unsafe: one or more ZFS-critical symbols are EXPORT_SYMBOL_GPL
#   2 - Could not determine (probe inconclusive, treat as unsafe)
# =============================================================================
set -euo pipefail

LINUX_DIR="${1:-}"
LINUX_OBJ="${2:-$LINUX_DIR}"
ARCH="${ARCH:-$(uname -m)}"
VERBOSE="${VERBOSE:-0}"

_log()  { echo "[probe_gpl_symbols] $*" >&2; }
_dbg()  { [[ "$VERBOSE" == "1" ]] && echo "[probe_gpl_symbols][DBG] $*" >&2 || true; }
_warn() { echo "[probe_gpl_symbols][WARN] $*" >&2; }

# ---------------------------------------------------------------------------
# Only ARM/AArch64 kernels have the NEON GPL symbol problem.
# x86 uses kernel_fpu_begin (also GPL-only on some kernels) — handled
# separately in the ZFS configure probes for modern ZFS versions.
# ---------------------------------------------------------------------------
case "$ARCH" in
  aarch64|arm64|arm)
    _dbg "Architecture $ARCH requires GPL symbol probe."
    ;;
  *)
    _log "Architecture $ARCH: NEON GPL probe not required. Safe."
    exit 0
    ;;
esac

# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
if [[ -z "$LINUX_DIR" ]]; then
  _warn "LINUX_DIR not specified. Cannot probe. Treating as unsafe."
  exit 2
fi

if [[ ! -d "$LINUX_DIR" ]]; then
  _warn "LINUX_DIR '$LINUX_DIR' does not exist. Treating as unsafe."
  exit 2
fi

# ---------------------------------------------------------------------------
# Method 1: Check Module.symvers (most reliable — present after kernel build)
# ---------------------------------------------------------------------------
SYMVERS="${LINUX_OBJ}/Module.symvers"
if [[ -f "$SYMVERS" ]]; then
  _dbg "Probing via Module.symvers: $SYMVERS"

  # Format: <crc> <symbol_name> <module> <export_type>
  # export_type is one of: EXPORT_SYMBOL, EXPORT_SYMBOL_GPL,
  #                        EXPORT_SYMBOL_GPL_FUTURE, EXPORT_SYMBOL_NS_GPL, ...
  GPL_ONLY_SYMS=()
  # Module.symvers CRC field may be "0xABCD" (with 0x prefix) or "ABCD" (without).
  # Pattern: optional 0x, then hex digits, then whitespace, then symbol name, then whitespace.
  SYMVER_PAT_PFX="^(0x)?[[:xdigit:]]+"

  for sym in kernel_neon_begin kernel_neon_end \
             bpf_trace_run1 bpf_trace_run2 bpf_trace_run3 \
             bpf_trace_run4 bpf_trace_run5; do
    if grep -qP "${SYMVER_PAT_PFX}\s+${sym}\s" "$SYMVERS"; then
      # Symbol exists — check if GPL-only
      EXPORT_TYPE=$(grep -P "${SYMVER_PAT_PFX}\s+${sym}\s" "$SYMVERS" \
                    | awk '{print $NF}')
      _dbg "Symbol $sym -> $EXPORT_TYPE"
      case "$EXPORT_TYPE" in
        *GPL*)
          GPL_ONLY_SYMS+=("$sym ($EXPORT_TYPE)")
          ;;
        *)
          _dbg "Symbol $sym is not GPL-only: $EXPORT_TYPE"
          ;;
      esac
    else
      _dbg "Symbol $sym not found in Module.symvers (may not exist on this arch/config)"
    fi
  done

  if [[ ${#GPL_ONLY_SYMS[@]} -gt 0 ]]; then
    _log "GPL-only symbols detected:"
    for s in "${GPL_ONLY_SYMS[@]}"; do
      _log "  -> $s"
    done
    _log "ZFS (CDDL) CANNOT use these symbols. Building without NEON."
    exit 1
  fi

  _log "No GPL-only NEON/BPF symbols found in Module.symvers. Safe to build with NEON."
  exit 0
fi

# ---------------------------------------------------------------------------
# Method 2: Grep kernel source for EXPORT_SYMBOL_GPL declarations.
# Less accurate (the source might differ from what was compiled), but useful
# when Module.symvers is absent (e.g. using kernel-headers package only).
# ---------------------------------------------------------------------------
_warn "Module.symvers not found at $SYMVERS. Falling back to source grep."

FPSIMD_C="${LINUX_DIR}/arch/arm64/kernel/fpsimd.c"
if [[ -f "$FPSIMD_C" ]]; then
  _dbg "Checking $FPSIMD_C for EXPORT_SYMBOL_GPL(kernel_neon_begin)"
  if grep -q 'EXPORT_SYMBOL_GPL(kernel_neon_begin)' "$FPSIMD_C"; then
    _log "EXPORT_SYMBOL_GPL(kernel_neon_begin) found in fpsimd.c"
    _log "Linux >=6.2 aarch64 pattern confirmed. ZFS cannot use NEON."
    exit 1
  else
    _log "kernel_neon_begin is not EXPORT_SYMBOL_GPL in this source tree. Safe."
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Method 3: Kernel version heuristic.
# Linux 6.2 is where kernel_neon_begin became EXPORT_SYMBOL_GPL on arm64.
# Use this as a last resort.
# ---------------------------------------------------------------------------
_warn "Cannot find fpsimd.c at $FPSIMD_C. Using kernel version heuristic."

VERSION_H="${LINUX_OBJ}/include/generated/utsrelease.h"
if [[ -f "$VERSION_H" ]]; then
  KVER=$(grep -oP '(?<=UTS_RELEASE ")[^"]+' "$VERSION_H" || true)
  _dbg "Detected kernel version: $KVER"

  KMAJ=$(echo "$KVER" | cut -d. -f1)
  KMIN=$(echo "$KVER" | cut -d. -f2)

  if [[ -n "$KMAJ" && -n "$KMIN" ]]; then
    # Heuristic: kernel_neon_begin became GPL-only starting in 6.2
    if { [[ "$KMAJ" -gt 6 ]] || { [[ "$KMAJ" -eq 6 ]] && [[ "$KMIN" -ge 2 ]]; }; }; then
      _log "Kernel version $KVER >= 6.2: assuming kernel_neon_begin is EXPORT_SYMBOL_GPL."
      _log "ZFS (CDDL) cannot safely use NEON on this kernel."
      exit 1
    else
      _log "Kernel version $KVER < 6.2: assuming kernel_neon_begin is safe."
      exit 0
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Inconclusive — treat as unsafe (fail-safe)
# ---------------------------------------------------------------------------
_warn "All probe methods inconclusive. Treating NEON symbols as GPL-only (safe fallback)."
exit 2
