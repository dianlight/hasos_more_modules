#!/usr/bin/env bash
# =============================================================================
# tests/test_probe_gpl_symbols.sh
#
# Unit tests for scripts/probe_gpl_symbols.sh
# Tests all three probe methods and all relevant scenarios.
#
# Usage:
#   bash tests/test_probe_gpl_symbols.sh
#
# Exit codes:
#   0  - all tests passed
#   1  - one or more tests failed
# =============================================================================
set -euo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/probe_gpl_symbols.sh"
TMPDIR_BASE=$(mktemp -d)
trap 'rm -rf "$TMPDIR_BASE"' EXIT

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_check() {
  local name="$1" expected="$2"
  shift 2
  local actual exit_code
  actual=$("$@" 2>/dev/null) || exit_code=$?
  exit_code=${exit_code:-0}

  if [[ "$exit_code" == "$expected" ]]; then
    echo "  ✅  $name (exit=$exit_code)"
    ((PASS++)) || true
  else
    echo "  ❌  $name (expected exit=$expected, got exit=$exit_code)"
    ((FAIL++)) || true
  fi
}

_make_symvers() {
  local dir="$1"; shift
  mkdir -p "$dir"
  printf '%s\n' "$@" > "$dir/Module.symvers"
}

_make_fpsimd() {
  local dir="$1" content="$2"
  mkdir -p "$dir/arch/arm64/kernel"
  echo "$content" > "$dir/arch/arm64/kernel/fpsimd.c"
}

_make_utsrelease() {
  local dir="$1" ver="$2"
  mkdir -p "$dir/include/generated"
  echo "#define UTS_RELEASE \"${ver}\"" > "$dir/include/generated/utsrelease.h"
}

# ---------------------------------------------------------------------------
# Test group 1: Architecture gate
# ---------------------------------------------------------------------------
echo "=== Architecture gate ==="

D="$TMPDIR_BASE/t1"
_make_symvers "$D"  # empty symvers

_check "x86_64 always safe (exit 0)"   0  env ARCH=x86_64  bash "$SCRIPT" "$D" "$D"
_check "x86 alias always safe (exit 0)" 0  env ARCH=x86    bash "$SCRIPT" "$D" "$D"

echo ""

# ---------------------------------------------------------------------------
# Test group 2: Method 1 — Module.symvers with 0x-prefixed CRC
# ---------------------------------------------------------------------------
echo "=== Method 1: Module.symvers (0x-prefixed CRC) ==="

D="$TMPDIR_BASE/t2"

# Scenario: GPL-only symbols → expect exit 1
_make_symvers "$D" \
  $'0xaabbccdd\tkernel_neon_begin\tvmlinux\tEXPORT_SYMBOL_GPL' \
  $'0x11223344\tkernel_neon_end\tvmlinux\tEXPORT_SYMBOL_GPL' \
  $'0xdeadbeef\tkmalloc\tvmlinux\tEXPORT_SYMBOL'
_check "GPL-only neon → exit 1" 1  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

# Scenario: plain EXPORT_SYMBOL → expect exit 0
_make_symvers "$D" \
  $'0xaabbccdd\tkernel_neon_begin\tvmlinux\tEXPORT_SYMBOL' \
  $'0x11223344\tkernel_neon_end\tvmlinux\tEXPORT_SYMBOL'
_check "plain EXPORT_SYMBOL neon → exit 0" 0  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

# Scenario: only bpf_trace_run GPL-only → expect exit 1
_make_symvers "$D" \
  $'0xaabbccdd\tkernel_neon_begin\tvmlinux\tEXPORT_SYMBOL' \
  $'0x99887766\tbpf_trace_run2\tvmlinux\tEXPORT_SYMBOL_GPL'
_check "bpf_trace_run GPL-only → exit 1" 1  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

# Scenario: bpf_trace_run EXPORT_SYMBOL (not GPL) → exit 0
_make_symvers "$D" \
  $'0xaabbccdd\tkernel_neon_begin\tvmlinux\tEXPORT_SYMBOL' \
  $'0x99887766\tbpf_trace_run2\tvmlinux\tEXPORT_SYMBOL'
_check "bpf_trace_run plain → exit 0" 0  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

echo ""

# ---------------------------------------------------------------------------
# Test group 3: Method 1 — Module.symvers without 0x prefix
# ---------------------------------------------------------------------------
echo "=== Method 1: Module.symvers (bare hex CRC, no 0x prefix) ==="

D="$TMPDIR_BASE/t3"
_make_symvers "$D" \
  $'aabbccdd\tkernel_neon_begin\tvmlinux\tEXPORT_SYMBOL_GPL'
_check "bare hex CRC GPL-only → exit 1" 1  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

_make_symvers "$D" \
  $'aabbccdd\tkernel_neon_begin\tvmlinux\tEXPORT_SYMBOL'
_check "bare hex CRC plain → exit 0" 0  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

echo ""

# ---------------------------------------------------------------------------
# Test group 4: Method 2 — fpsimd.c source grep (no Module.symvers)
# ---------------------------------------------------------------------------
echo "=== Method 2: fpsimd.c source grep (fallback) ==="

D="$TMPDIR_BASE/t4"
# No Module.symvers — force fallback to method 2

_make_fpsimd "$D" "EXPORT_SYMBOL_GPL(kernel_neon_begin);"
_check "fpsimd has EXPORT_SYMBOL_GPL → exit 1" 1  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

_make_fpsimd "$D" "EXPORT_SYMBOL(kernel_neon_begin);"
_check "fpsimd has EXPORT_SYMBOL → exit 0" 0  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

echo ""

# ---------------------------------------------------------------------------
# Test group 5: Method 3 — kernel version heuristic (no symvers, no source)
# ---------------------------------------------------------------------------
echo "=== Method 3: Kernel version heuristic ==="

D="$TMPDIR_BASE/t5"
# Neither Module.symvers nor fpsimd.c — only utsrelease.h

_make_utsrelease "$D" "6.2.0-haos"
_check "kernel 6.2.0 (>=6.2) → exit 1 (heuristic)" 1  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

_make_utsrelease "$D" "6.6.31-v8-haos"
_check "kernel 6.6.x (>=6.2) → exit 1 (heuristic)" 1  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

_make_utsrelease "$D" "6.1.0-haos"
_check "kernel 6.1.x (<6.2) → exit 0 (heuristic)" 0  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

_make_utsrelease "$D" "5.15.0"
_check "kernel 5.15.x (<6.2) → exit 0 (heuristic)" 0  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

echo ""

# ---------------------------------------------------------------------------
# Test group 6: Method 3 — inconclusive (no fallback available) → exit 2
# ---------------------------------------------------------------------------
echo "=== Method 3: Inconclusive (empty dir, aarch64) ==="

D="$TMPDIR_BASE/t6_empty"
mkdir -p "$D"
_check "empty dir, no methods → exit 2" 2  env ARCH=aarch64 bash "$SCRIPT" "$D" "$D"

echo ""

# ---------------------------------------------------------------------------
# Test group 7: Missing arguments
# ---------------------------------------------------------------------------
echo "=== Missing arguments ==="

_check "no args → exit 2" 2  env ARCH=aarch64 bash "$SCRIPT"

echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
TOTAL=$((PASS + FAIL))
echo "=== Summary: ${PASS}/${TOTAL} tests passed ==="
if [[ "$FAIL" -gt 0 ]]; then
  echo "  ❌  ${FAIL} test(s) FAILED"
  exit 1
else
  echo "  🎉  All tests passed!"
  exit 0
fi
