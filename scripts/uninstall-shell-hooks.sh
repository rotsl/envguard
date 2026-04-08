#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.
#
# uninstall-shell-hooks.sh - Remove envguard shell integration hooks
#
# This script removes envguard integration from your shell's RC file
# that was previously installed by install-shell-hooks.sh.

set -euo pipefail

# --- Configuration ---
ENVGUARD_RC_TAG="# >>> envguard >>>"
ENVGUARD_RC_UNTAG="# <<< envguard <<<"

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

# --- Detect shell ---
detect_shell() {
    if [ -n "${ZSH_VERSION:-}" ]; then
        echo "zsh"
    elif [ -n "${BASH_VERSION:-}" ]; then
        echo "bash"
    elif [ -n "${FISH_VERSION:-}" ]; then
        echo "fish"
    else
        echo "unknown"
    fi
}

# --- Determine RC file path ---
get_rc_path() {
    local shell_type="$1"
    local home_dir
    home_dir="$(cd ~ && pwd)"

    case "$shell_type" in
        zsh)
            if [ -f "${home_dir}/.zshrc" ] && grep -qF "$ENVGUARD_RC_TAG" "${home_dir}/.zshrc" 2>/dev/null; then
                echo "${home_dir}/.zshrc"
            elif [ -f "${home_dir}/.zprofile" ] && grep -qF "$ENVGUARD_RC_TAG" "${home_dir}/.zprofile" 2>/dev/null; then
                echo "${home_dir}/.zprofile"
            elif [ -f "${home_dir}/.zshrc" ]; then
                echo "${home_dir}/.zshrc"
            else
                echo "${home_dir}/.zprofile"
            fi
            ;;
        bash)
            if [[ "$(uname)" == "Darwin" ]]; then
                if [ -f "${home_dir}/.bash_profile" ] && grep -qF "$ENVGUARD_RC_TAG" "${home_dir}/.bash_profile" 2>/dev/null; then
                    echo "${home_dir}/.bash_profile"
                elif [ -f "${home_dir}/.bashrc" ] && grep -qF "$ENVGUARD_RC_TAG" "${home_dir}/.bashrc" 2>/dev/null; then
                    echo "${home_dir}/.bashrc"
                elif [ -f "${home_dir}/.bash_profile" ]; then
                    echo "${home_dir}/.bash_profile"
                else
                    echo "${home_dir}/.bashrc"
                fi
            else
                if [ -f "${home_dir}/.bashrc" ]; then
                    echo "${home_dir}/.bashrc"
                else
                    echo "${home_dir}/.bash_profile"
                fi
            fi
            ;;
        fish)
            echo "${home_dir}/.config/fish/config.fish"
            ;;
        *)
            error "Unsupported shell: $shell_type"
            return 1
            ;;
    esac
}

# --- Check if hooks are installed ---
hooks_installed() {
    local rc_path="$1"
    [ -f "$rc_path" ] && grep -qF "$ENVGUARD_RC_TAG" "$rc_path" 2>/dev/null
}

# --- Remove hooks using sed ---
remove_hooks_from_file() {
    local rc_path="$1"

    if [ ! -f "$rc_path" ]; then
        warn "RC file not found: $rc_path"
        return 1
    fi

    if ! hooks_installed "$rc_path"; then
        warn "No envguard hooks found in $rc_path"
        return 0
    fi

    # Create backup
    local backup_path="${rc_path}.envguard-backup.$(date +%Y%m%d%H%M%S)"
    cp "$rc_path" "$backup_path"
    info "Backup created: $backup_path"

    # Remove lines between the tags (inclusive), using sed
    # This works on both GNU sed (Linux) and BSD sed (macOS)
    if sed --version &>/dev/null 2>&1; then
        # GNU sed
        sed -i "/${ENVGUARD_RC_TAG}/,/${ENVGUARD_RC_UNTAG}/d" "$rc_path"
    else
        # BSD sed (macOS) - need in-place with extension
        local tmp_path="${rc_path}.tmp.$$"
        sed "/${ENVGUARD_RC_TAG}/,/${ENVGUARD_RC_UNTAG}/d" "$rc_path" > "$tmp_path"
        mv "$tmp_path" "$rc_path"
    fi

    # Clean up trailing blank lines
    if sed --version &>/dev/null 2>&1; then
        sed -i -e :a -e '/^\n*$/{$d;N;ba;}' "$rc_path"
    else
        local tmp_path="${rc_path}.tmp.$$"
        sed -e :a -e '/^\n*$/{$d;N;ba;}' "$rc_path" > "$tmp_path"
        mv "$tmp_path" "$rc_path"
    fi

    info "Removed envguard hooks from ${BLUE}$rc_path${NC}"
}

# --- Try Python module first ---
uninstall_via_python() {
    if command -v envguard &>/dev/null; then
        if envguard uninstall-shell-hooks 2>/dev/null; then
            info "Hooks removed via envguard Python module."
            return 0
        fi
    fi
    return 1
}

# --- Main ---
main() {
    local shell_type="${1:-$(detect_shell)}"
    local rc_path

    echo -e "${BOLD}envguard - Uninstall Shell Hooks${NC}"
    echo ""

    case "$shell_type" in
        zsh|bash|fish) ;;
        *)
            error "Unknown or unsupported shell: '$shell_type'"
            echo "Supported shells: zsh, bash, fish"
            echo "Usage: $0 [zsh|bash|fish]"
            exit 1
            ;;
    esac

    info "Detected shell: ${BLUE}$shell_type${NC}"

    # Try Python module first
    if uninstall_via_python; then
        info ""
        info "${GREEN}Done!${NC} Restart your shell for changes to take effect."
        return 0
    fi

    # Fall back to shell script
    rc_path="$(get_rc_path "$shell_type")"
    info "RC file: ${BLUE}$rc_path${NC}"

    remove_hooks_from_file "$rc_path"

    info ""
    info "${GREEN}Done!${NC} Restart your shell for changes to take effect."
}

main "$@"
