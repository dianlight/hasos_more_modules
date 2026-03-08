#!/usr/bin/env bash
# patch_config.sh – Patch the HAOS kernel configuration for out-of-tree module
# compilation.
#
# Usage:
#   scripts/patch_config.sh <path-to-kernel.config> [<board>] [<modules-config>]
#
# Arguments:
#   <path-to-kernel.config>  Absolute or relative path to the kernel.config
#                             file that should be patched in place.
#   <board>                   Target board name (e.g. generic_x86_64, rpi4_64).
#                             Optional; used only for informational messages.
#   <modules-config>          Path to module/config definition file.
#                             Optional; defaults to config/modules.json.
#
# The script loads all CONFIG_* assignments from config/modules.json and applies
# them to the selected kernel.config file.

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <path-to-kernel.config> [<board>] [<modules-config>]" >&2
    exit 1
fi

CONFIG_FILE="$1"
BOARD="${2:-unknown}"
MODULES_CONFIG="${3:-config/modules.json}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
    echo "[ERROR] Config file not found: ${CONFIG_FILE}" >&2
    exit 1
fi

if [[ ! -f "${MODULES_CONFIG}" ]]; then
    echo "[ERROR] Modules config file not found: ${MODULES_CONFIG}" >&2
    exit 1
fi

echo "[INFO] Patching kernel config: ${CONFIG_FILE} (board=${BOARD})"
echo "[INFO] Using module config: ${MODULES_CONFIG}"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

# set_config_value <symbol> <value>
#   Ensures <symbol>=<value> is present; only replaces existing values if
#   they are disabled (n/f).
set_config_value() {
    local sym="$1"
    local val="$2"
    if grep -qE "^${sym}=" "${CONFIG_FILE}"; then
        local current_value
        current_value=$(grep -E "^${sym}=" "${CONFIG_FILE}" | head -n1 | cut -d'=' -f2-)

        if [[ "${current_value}" == "n" || "${current_value}" == "f" ]]; then
            sed -i "s|^${sym}=.*|${sym}=${val}|" "${CONFIG_FILE}"
        fi
    elif grep -qE "^# ${sym} is not set" "${CONFIG_FILE}"; then
        sed -i "s|^# ${sym} is not set|${sym}=${val}|" "${CONFIG_FILE}"
    else
        echo "${sym}=${val}" >> "${CONFIG_FILE}"
    fi
}

# ---------------------------------------------------------------------------
# Apply patches
# ---------------------------------------------------------------------------

echo "[INFO] Applying configured symbols ..."
ASSIGNMENTS_JSON=$(python3 scripts/modules_config.py --config "${MODULES_CONFIG}" config-assignments-json)
mapfile -t ASSIGNMENTS < <(echo "${ASSIGNMENTS_JSON}" | jq -r '.[] | "\(.symbol)|\(.type)|\(.value)"')

if [[ ${#ASSIGNMENTS[@]} -eq 0 ]]; then
    echo "[ERROR] No CONFIG_* assignments found in ${MODULES_CONFIG}" >&2
    exit 1
fi

PATCHED_SYMBOLS=()
for entry in "${ASSIGNMENTS[@]}"; do
    IFS='|' read -r sym value_type value <<< "${entry}"
    if [[ "${value_type}" == "string" ]]; then
        rendered_value="\"${value}\""
    else
        rendered_value="${value}"
    fi
    echo "  [set] ${sym}=${rendered_value}"
    set_config_value "${sym}" "${rendered_value}"
    PATCHED_SYMBOLS+=("${sym}")
done

echo "[INFO] Patch complete."

# ---------------------------------------------------------------------------
# Verification – print the patched values so CI logs are easy to audit.
# ---------------------------------------------------------------------------
echo ""
echo "[INFO] Patched configuration summary:"
for sym in "${PATCHED_SYMBOLS[@]}"; do
    value=$(grep -E "^${sym}=" "${CONFIG_FILE}" 2>/dev/null || echo "# ${sym} not found")
    echo "  ${value}"
done
