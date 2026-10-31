#!/usr/bin/env bash
# patch_config.sh – Patch the HAOS kernel configuration for out-of-tree module
# compilation.
#
# Usage:
#   scripts/patch_config.sh <path-to-kernel.config> [<board>] [<modules-config>] [--only-modules <list>]
#
# Arguments:
#   <path-to-kernel.config>  Absolute or relative path to the kernel.config
#                             file that should be patched in place.
#   <board>                   Target board name (e.g. generic_x86_64, rpi4_64).
#                             Optional; used only for informational messages.
#   <modules-config>          Path to module/config definition file.
#                             Optional; defaults to config/modules.json.
#   --only-modules <list>     Comma-separated module names to apply configs for.
#                             Optional; defaults to all modules.
#   --force                   Apply the requested value even when the config
#                             already sets a different one.  Upgrades only
#                             (n/f → m/y, m → y); a `=y` is never demoted to
#                             `=m`, since a built-in module cannot be replaced
#                             by a loadable one.
#
# The script loads CONFIG_* assignments from config/modules.json and applies
# them to the selected kernel.config file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <path-to-kernel.config> [<board>] [<modules-config>] [--only-modules <comma-list>]" >&2
    exit 1
fi

CONFIG_FILE="$1"
BOARD="${2:-unknown}"
MODULES_CONFIG="${3:-${REPO_ROOT}/config/modules.json}"

# Parse optional flags after positional args
shift; shift 2>/dev/null || true; shift 2>/dev/null || true
ONLY_MODULES=""
FORCE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --only-modules)
            ONLY_MODULES="$2"
            shift 2
            ;;
        --force)
            FORCE=1
            shift
            ;;
        *)
            echo "[WARN] Unknown argument: $1" >&2
            shift
            ;;
    esac
done

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

# sed_inplace <expr> <file>
#   Portable in-place sed for GNU/Linux and BSD/macOS.
sed_inplace() {
    local expr="$1"
    local file="$2"
    if sed --version >/dev/null 2>&1; then
        sed -i "${expr}" "${file}"
    else
        sed -i '' "${expr}" "${file}"
    fi
}

# set_config_value <symbol> <value> [<force>]
#   Ensures <symbol>=<value> is present.  Without <force>, an existing value is
#   only replaced when it is disabled (n/f).  With <force>, the requested value
#   wins, except for a `=y` → `=m` demotion, which is refused because a module
#   built into vmlinux cannot be replaced by a loadable one.
set_config_value() {
    local sym="$1"
    local val="$2"
    local force="${3:-0}"
    if grep -qE "^${sym}=" "${CONFIG_FILE}"; then
        local current_value
        current_value=$(grep -E "^${sym}=" "${CONFIG_FILE}" | head -n1 | cut -d'=' -f2-)

        if [[ "${current_value}" == "${val}" ]]; then
            return 0
        fi

        if [[ "${force}" -eq 1 ]]; then
            if [[ "${current_value}" == "y" && "${val}" == "m" ]]; then
                echo "  [warn] ${sym} is built-in (=y); keeping it instead of =m"
                return 0
            fi
            sed_inplace "s|^${sym}=.*|${sym}=${val}|" "${CONFIG_FILE}"
            return 0
        fi

        if [[ "${current_value}" == "n" || "${current_value}" == "f" ]]; then
            sed_inplace "s|^${sym}=.*|${sym}=${val}|" "${CONFIG_FILE}"
        fi
    elif grep -qE "^# ${sym} is not set" "${CONFIG_FILE}"; then
        sed_inplace "s|^# ${sym} is not set|${sym}=${val}|" "${CONFIG_FILE}"
    else
        echo "${sym}=${val}" >> "${CONFIG_FILE}"
    fi
}

# ---------------------------------------------------------------------------
# Apply patches
# ---------------------------------------------------------------------------

echo "[INFO] Applying configured symbols ..."
ONLY_MODULES_ARG=""
if [[ -n "${ONLY_MODULES}" ]]; then
    ONLY_MODULES_ARG="--only-modules ${ONLY_MODULES}"
    echo "[INFO] Filtering to modules: ${ONLY_MODULES}"
fi
ASSIGNMENTS_JSON=$(python3 "${SCRIPT_DIR}/modules_config.py" --config "${MODULES_CONFIG}" --board "${BOARD}" config-assignments-json ${ONLY_MODULES_ARG})
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
    set_config_value "${sym}" "${rendered_value}" "${FORCE}"
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
