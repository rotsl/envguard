#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.
#
# install-launch-agent.sh - Install envguard update LaunchAgent on macOS
#
# This script installs a macOS LaunchAgent that periodically runs
# `envguard update` in the background to keep envguard up to date.

set -euo pipefail

# --- Configuration ---
PLIST_NAME="com.envguard.update"
PLIST_SRC_DIR=""
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Look for plist in launchd/ directory next to this script's project root
if [ -f "${PROJECT_ROOT}/launchd/${PLIST_NAME}.plist" ]; then
    PLIST_SRC_DIR="${PROJECT_ROOT}/launchd"
elif [ -f "$(dirname "$0")/../launchd/${PLIST_NAME}.plist" ]; then
    PLIST_SRC_DIR="$(cd "$(dirname "$0")/../launchd" && pwd)"
else
    PLIST_SRC_DIR=""
fi

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/.envguard/logs"

# --- Colors ---
if [[ -t 1 ]] && command -v tput &>/dev/null && [[ $(tput colors 2>/dev/null || echo 0) -ge 8 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' NC=''
fi

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# --- Check platform ---
check_platform() {
    if [[ "$(uname)" != "Darwin" ]]; then
        error "LaunchAgents are only supported on macOS."
        error "Current platform: $(uname -s)"
        exit 1
    fi
}

# --- Find envguard binary ---
find_envguard_binary() {
    local binary=""

    # Check common locations
    for path in \
        "$(which envguard 2>/dev/null)" \
        "${HOME}/.local/bin/envguard" \
        "/usr/local/bin/envguard" \
        "/opt/homebrew/bin/envguard"; do
        if [ -n "$path" ] && [ -x "$path" ]; then
            binary="$path"
            break
        fi
    done

    # If not found, try the development install
    if [ -z "$binary" ] && [ -f "${PROJECT_ROOT}/src/envguard/cli.py" ]; then
        binary="$(which python3) -m envguard"
        warn "Using development install: $binary"
    fi

    if [ -z "$binary" ]; then
        error "envguard binary not found."
        error "Install envguard first: pip install -e ${PROJECT_ROOT}"
        exit 1
    fi

    echo "$binary"
}

# --- Generate plist if source not found ---
generate_plist() {
    local envguard_bin="$1"
    local plist_dest="$2"

    cat > "$plist_dest" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${envguard_bin}</string>
        <string>update</string>
        <string>--check</string>
    </array>
    <key>StartInterval</key>
    <integer>86400</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/Users/Shared</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/update-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/update-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST_EOF

    info "Generated plist: $plist_dest"
}

# --- Install LaunchAgent ---
install_agent() {
    local envguard_bin
    envguard_bin="$(find_envguard_binary)"

    info "Using envguard: ${BLUE}${envguard_bin}${NC}"

    # Try the Python module first
    if command -v envguard &>/dev/null; then
        if envguard install-launch-agent 2>/dev/null; then
            info ""
            info "${GREEN}LaunchAgent installed successfully via Python module.${NC}"
            info "envguard will check for updates every 24 hours."
            return 0
        fi
        warn "Python module installation failed, falling back to manual install."
    fi

    # Create directories
    mkdir -p "$LAUNCH_AGENTS_DIR"
    mkdir -p "$LOG_DIR"

    local plist_dest="${LAUNCH_AGENTS_DIR}/${PLIST_NAME}.plist"

    # Unload if already loaded
    if launchctl list "${PLIST_NAME}" &>/dev/null 2>&1; then
        info "Unloading existing LaunchAgent..."
        launchctl bootout "gui/$(id -u)/${PLIST_NAME}" 2>/dev/null || \
            launchctl unload "$plist_dest" 2>/dev/null || true
    fi

    # Copy or generate plist
    if [ -n "$PLIST_SRC_DIR" ] && [ -f "${PLIST_SRC_DIR}/${PLIST_NAME}.plist" ]; then
        # Use the project plist but update the binary path
        local tmp_plist
        tmp_plist="$(mktemp)"
        sed "s|/usr/local/bin/envguard|${envguard_bin}|g" \
            "${PLIST_SRC_DIR}/${PLIST_NAME}.plist" > "$tmp_plist"
        # Also update log directory
        local tmp_plist_fixed
        tmp_plist_fixed="$(mktemp)"
        sed "s|/Users/Shared/.envguard/logs|${LOG_DIR}|g" "$tmp_plist" > "$tmp_plist_fixed"
        mv "$tmp_plist_fixed" "$tmp_plist"
        cp "$tmp_plist" "$plist_dest"
        rm -f "$tmp_plist"
        info "Installed plist from: ${PLIST_SRC_DIR}/${PLIST_NAME}.plist"
    else
        generate_plist "$envguard_bin" "$plist_dest"
    fi

    # Load the LaunchAgent
    launchctl bootstrap "gui/$(id -u)" "$plist_dest" 2>/dev/null || \
        launchctl load "$plist_dest" 2>/dev/null

    # Verify
    if launchctl list "${PLIST_NAME}" &>/dev/null 2>&1; then
        info ""
        info "${GREEN}LaunchAgent installed and loaded successfully.${NC}"
        info "  Label:    ${PLIST_NAME}"
        info "  Plist:    ${plist_dest}"
        info "  Binary:   ${envguard_bin}"
        info "  Interval: Every 24 hours"
        info "  Logs:     ${LOG_DIR}/"
    else
        warn "LaunchAgent plist installed but may not be loaded."
        info "  Try manually: launchctl load ${plist_dest}"
    fi
}

# --- Main ---
main() {
    echo -e "${BOLD}envguard - Install LaunchAgent${NC}"
    echo ""

    check_platform
    install_agent
}

main "$@"
