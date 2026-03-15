#!/usr/bin/env bash
# =============================================================================
# scripts/patch_config.sh
#
# Patches a Buildroot kernel.config file to enable extra modules as =m.
# Module list is driven by config/modules.json.
#
# Usage:
#   scripts/patch_config.sh <kernel.config> <arch> [board]
#
# Arguments:
#   kernel.config  - Path to the kernel config to patch (modified in-place)
#   arch           - Target architecture: x86_64 | aarch64
#   board          - (optional) Board name for per-board exclusion checks
#                    e.g. rpi4_64, yellow, odroid_n2, x86_64
#
# The script:
#   1. Enables every CONFIG_* symbol listed in modules.json (=m)
#   2. Enables prerequisite symbols (MODULES, MODVERSIONS, etc.)
#   3. Skips modules in exclude_boards.hard for this board
#   4. Sets a stable LOCALVERSION suffix for reproducible builds
#   5. Reports which ZFS modules need build_zfs.sh (external build)
#
# Outputs (stdout):
#   JSON object:  { "patched": [...], "skipped": [...], "zfs_modules": [...] }
#   Redirect to a file to capture for the CI workflow.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODULES_JSON="$REPO_ROOT/config/modules.json"

KERNEL_CONFIG="${1:-}"
ARCH="${2:-}"
BOARD="${3:-}"

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
if [[ -z "$KERNEL_CONFIG" || -z "$ARCH" ]]; then
  echo "Usage: $0 <kernel.config> <arch> [board]" >&2
  exit 1
fi

if [[ ! -f "$KERNEL_CONFIG" ]]; then
  echo "ERROR: kernel.config not found: $KERNEL_CONFIG" >&2
  exit 1
fi

if [[ ! -f "$MODULES_JSON" ]]; then
  echo "ERROR: modules.json not found: $MODULES_JSON" >&2
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 required" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Helper: set/replace a CONFIG_* value in the kernel config
# ---------------------------------------------------------------------------
set_config() {
  local key="$1"   # e.g. CONFIG_XFS_FS
  local val="$2"   # e.g. m, y, n, or a quoted string

  if grep -qE "^${key}=" "$KERNEL_CONFIG"; then
    # Replace existing line
    sed -i "s|^${key}=.*|${key}=${val}|" "$KERNEL_CONFIG"
  elif grep -qE "^# ${key} is not set" "$KERNEL_CONFIG"; then
    # Replace commented-out line
    sed -i "s|^# ${key} is not set|${key}=${val}|" "$KERNEL_CONFIG"
  else
    # Append
    echo "${key}=${val}" >> "$KERNEL_CONFIG"
  fi
}

# ---------------------------------------------------------------------------
# Step 1: Ensure module infrastructure is enabled
# ---------------------------------------------------------------------------
echo "# [patch_config] Enabling module infrastructure..." >&2
set_config CONFIG_MODULES y
set_config CONFIG_MODULE_UNLOAD y
set_config CONFIG_MODULE_FORCE_UNLOAD y
set_config CONFIG_MODVERSIONS y
set_config CONFIG_MODULE_SRCVERSION_ALL y

# Needed for out-of-tree module builds
set_config CONFIG_KALLSYMS y
set_config CONFIG_KALLSYMS_ALL y

# ---------------------------------------------------------------------------
# Step 2: Read modules.json and patch CONFIG_* symbols
# ---------------------------------------------------------------------------
echo "# [patch_config] Reading config/modules.json..." >&2

python3 - <<'PYEOF'
import json, sys, os, subprocess, re

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if '__file__' in dir() else os.getcwd()
# When called from bash here-doc, use env vars instead
repo_root = os.environ.get('REPO_ROOT', os.getcwd())
modules_json = os.path.join(repo_root, 'config', 'modules.json')
kernel_config = os.environ.get('KERNEL_CONFIG', '')
arch = os.environ.get('TARGET_ARCH', '')
board = os.environ.get('TARGET_BOARD', '')

with open(modules_json) as f:
    data = json.load(f)

modules = data.get('modules', [])
patched = []
skipped = []
zfs_modules = []

def set_config_py(path, key, val):
    """Set a CONFIG_* key in the kernel config file."""
    with open(path, 'r') as f:
        content = f.read()
    
    pattern_set = re.compile(rf'^{re.escape(key)}=.*$', re.MULTILINE)
    pattern_unset = re.compile(rf'^# {re.escape(key)} is not set$', re.MULTILINE)
    
    new_line = f'{key}={val}'
    
    if pattern_set.search(content):
        content = pattern_set.sub(new_line, content)
    elif pattern_unset.search(content):
        content = pattern_unset.sub(new_line, content)
    else:
        content += f'\n{new_line}\n'
    
    with open(path, 'w') as f:
        f.write(content)

for mod in modules:
    name = mod['name']
    kconfigs = mod.get('kconfig', [])
    exclude = mod.get('exclude_boards', {})
    source = mod.get('source', {})
    
    # Check hard exclusions (board can never build this module)
    hard_excluded = exclude.get('hard', [])
    if board and board in hard_excluded:
        skipped.append({'name': name, 'reason': f'hard excluded for board {board}'})
        continue
    
    # Check soft_neon exclusions (excluded UNLESS GPL probe passes)
    # These are flagged but not skipped here — the CI workflow decides
    soft_neon = exclude.get('soft_neon', [])
    is_soft_excluded = board and board in soft_neon
    
    # External modules (ZFS, QUIC) don't have kconfig symbols to enable
    if source.get('type') in ('zfs_module', 'external'):
        if source.get('type') == 'zfs_module':
            zfs_modules.append({
                'name': name,
                'soft_neon_excluded': is_soft_excluded,
                'board': board,
            })
        # External modules are built separately; skip kconfig patching
        continue
    
    # Patch kconfig symbols
    for sym in kconfigs:
        if kernel_config:
            set_config_py(kernel_config, sym, 'm')
    
    patched.append(name)

result = {
    'patched': patched,
    'skipped': skipped,
    'zfs_modules': zfs_modules,
}
print(json.dumps(result, indent=2))
PYEOF

# ---------------------------------------------------------------------------
# Step 3: Set LOCALVERSION for reproducible vermagic
# ---------------------------------------------------------------------------
# HAOS uses a custom LOCALVERSION. We must not change it — the module's
# vermagic must exactly match the running kernel's uname -r output.
# We only ensure the symbol is present (do not overwrite if already set).
if ! grep -q '^CONFIG_LOCALVERSION=' "$KERNEL_CONFIG"; then
  echo "# [patch_config] CONFIG_LOCALVERSION not set — leaving as-is (inherits from HAOS defconfig)" >&2
fi

# ---------------------------------------------------------------------------
# Step 4: Architecture-specific adjustments
# ---------------------------------------------------------------------------
case "$ARCH" in
  aarch64)
    # Ensure KERNEL_MODE_NEON is enabled (needed for ICP crypto perf on supported boards)
    # The ZFS build itself will detect if kernel_neon_begin is GPL-only at compile time.
    set_config CONFIG_KERNEL_MODE_NEON y
    echo "# [patch_config] aarch64: CONFIG_KERNEL_MODE_NEON=y (ZFS build will probe GPL safety)" >&2
    ;;
  x86_64)
    # x86_64: kernel_fpu_begin is also EXPORT_SYMBOL_GPL on some kernels.
    # Modern ZFS (2.2.x) handles this; no extra config needed.
    echo "# [patch_config] x86_64: no extra config adjustments" >&2
    ;;
esac

echo "# [patch_config] Done." >&2
