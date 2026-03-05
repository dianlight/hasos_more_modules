#!/usr/bin/env bash
# patch_config.sh – Patch the HAOS kernel configuration for out-of-tree module
# compilation.
#
# Usage:
#   scripts/patch_config.sh <path-to-kernel.config> [<board>]
#
# Arguments:
#   <path-to-kernel.config>  Absolute or relative path to the kernel.config
#                             file that should be patched in place.
#   <board>                   Target board name (e.g. generic_x86_64, rpi4_64).
#                             Optional; used only for informational messages.
#
# The script performs the following changes:
#   1. Ensures CONFIG_MODULES=y (loadable module support is required).
#   2. Ensures CONFIG_LOCALVERSION="-haos" so the kernel version string matches.
#   3. Forces the following symbols to =m (compiled as loadable modules):
#        CONFIG_XFS_FS
#        CONFIG_NFS_FS       (NFS client)
#        CONFIG_NFS_V4       (NFSv4 client support)
#        CONFIG_NFSD         (NFS server)
#        CONFIG_NFSD_V4      (NFSv4 server support)
#        CONFIG_EXPORTFS     (export filesystem – required by nfsd)

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <path-to-kernel.config> [<board>]" >&2
    exit 1
fi

CONFIG_FILE="$1"
BOARD="${2:-unknown}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
    echo "[ERROR] Config file not found: ${CONFIG_FILE}" >&2
    exit 1
fi

echo "[INFO] Patching kernel config: ${CONFIG_FILE} (board=${BOARD})"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

# set_config_y <symbol>
#   Ensures <symbol>=y is present; replaces any existing assignment.
set_config_y() {
    local sym="$1"
    if grep -qE "^${sym}=" "${CONFIG_FILE}"; then
        sed -i "s|^${sym}=.*|${sym}=y|" "${CONFIG_FILE}"
    elif grep -qE "^# ${sym} is not set" "${CONFIG_FILE}"; then
        sed -i "s|^# ${sym} is not set|${sym}=y|" "${CONFIG_FILE}"
    else
        echo "${sym}=y" >> "${CONFIG_FILE}"
    fi
}

# set_config_m <symbol>
#   Ensures <symbol>=m is present; replaces any existing assignment.
set_config_m() {
    local sym="$1"
    if grep -qE "^${sym}=" "${CONFIG_FILE}"; then
        sed -i "s|^${sym}=.*|${sym}=m|" "${CONFIG_FILE}"
    elif grep -qE "^# ${sym} is not set" "${CONFIG_FILE}"; then
        sed -i "s|^# ${sym} is not set|${sym}=m|" "${CONFIG_FILE}"
    else
        echo "${sym}=m" >> "${CONFIG_FILE}"
    fi
}

# set_config_string <symbol> <value>
#   Ensures <symbol>="<value>" is present; replaces any existing assignment.
set_config_string() {
    local sym="$1"
    local val="$2"
    if grep -qE "^${sym}=" "${CONFIG_FILE}"; then
        sed -i "s|^${sym}=.*|${sym}=\"${val}\"|" "${CONFIG_FILE}"
    elif grep -qE "^# ${sym} is not set" "${CONFIG_FILE}"; then
        sed -i "s|^# ${sym} is not set|${sym}=\"${val}\"|" "${CONFIG_FILE}"
    else
        echo "${sym}=\"${val}\"" >> "${CONFIG_FILE}"
    fi
}

# ---------------------------------------------------------------------------
# Apply patches
# ---------------------------------------------------------------------------

echo "[INFO] Step 1: Ensuring CONFIG_MODULES=y ..."
set_config_y "CONFIG_MODULES"

echo "[INFO] Step 2: Ensuring CONFIG_LOCALVERSION=\"-haos\" ..."
set_config_string "CONFIG_LOCALVERSION" "-haos"

echo "[INFO] Step 3: Forcing filesystem modules to =m ..."
MODULES=(
    CONFIG_XFS_FS
    CONFIG_NFS_FS
    CONFIG_NFS_V4
    CONFIG_NFSD
    CONFIG_NFSD_V4
    CONFIG_EXPORTFS
)
for sym in "${MODULES[@]}"; do
    echo "  [m] ${sym}"
    set_config_m "${sym}"
done

echo "[INFO] Patch complete."

# ---------------------------------------------------------------------------
# Verification – print the patched values so CI logs are easy to audit.
# ---------------------------------------------------------------------------
echo ""
echo "[INFO] Patched configuration summary:"
for sym in CONFIG_MODULES CONFIG_LOCALVERSION "${MODULES[@]}"; do
    value=$(grep -E "^${sym}=" "${CONFIG_FILE}" 2>/dev/null || echo "# ${sym} not found")
    echo "  ${value}"
done
