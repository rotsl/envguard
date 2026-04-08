#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.
#
# uninstall-launch-agent.sh - Remove envguard update LaunchAgent on macOS
#
# This script removes the envguard LaunchAgent that was previously installed
# by install-launch-agent.sh.

set -euo pipefail

# --- Configuration ---
PLIST_NAME="com.envguard.update"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/${PLIST_NAME}.plist"
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

# --- Uninstall LaunchAgent ---
uninstall_agent() {
    # Try Python module first
    if command -v envguard &>/dev/null; then
        if envguard uninstall-launch-agent 2>/dev/null; then
            info ""
            info "${GREEN}LaunchAgent removed successfully via Python module.${NC}"
            return 0
        fi
        warn "Python module uninstall failed, falling back to manual removal."
    fi

    local was_loaded=false

    # Check if loaded
    if launchctl list "${PLIST_NAME}" &>/dev/null 2>&1; then
        was_loaded=true
        info "Unloading LaunchAgent: ${PLIST_NAME}..."

        # Try modern bootout first (macOS 11+), fall back to unload
        if ! launchctl bootout "gui/$(id -u)/${PLIST_NAME}" 2>/dev/null; then
            launchctl unload "$PLIST_PATH" 2>/dev/null || true
        fi
    fi

    # Remove plist file
    if [ -f "$PLIST_PATH" ]; then
        rm -f "$PLIST_PATH"
        info "Removed plist: ${BLUE}${PLIST_PATH}${NC}"
    else
        warn "Plist not found: $PLIST_PATH"
    fi

    # Offer to clean up logs
    if [ -d "$LOG_DIR" ]; then
        local log_count
        log_count="$(find "$LOG_DIR" -name "update.*.log" -type f 2>/dev/null | wc -l | tr -d ' ')"
        if [ "$log_count" -gt 0 ]; then
            echo ""
            read -p "Remove log files in ${LOG_DIR}? [y/N] " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -f "${LOG_DIR}"/update.*.log
                info "Removed ${log_count} log file(s)."
            else
                info "Log files preserved in ${LOG_DIR}"
            fi
        fi
    fi

    # Summary
    info ""
    info "${GREEN}LaunchAgent uninstalled.${NC}"
    if $was_loaded; then
        info "  Stopped:  ${PLIST_NAME}"
    fi
    info "  Removed:  ${PLIST_PATH}"
}

# --- Main ---
main() {
    echo -e "${BOLD}envguard - Uninstall LaunchAgent${NC}"
    echo ""

    check_platform
    uninstall_agent
}

main "$@"
