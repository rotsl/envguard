#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.
#
# install-shell-hooks.sh - Install envguard shell integration hooks
#
# This script installs envguard integration into your shell's RC file
# (e.g., .zshrc, .bashrc, .bash_profile) so that envguard can manage
# environment activation, PATH modification, and prompt enrichment.

set -euo pipefail

# --- Configuration ---
ENVGUARD_SCRIPT_NAME="install-shell-hooks.sh"
ENVGUARD_RC_TAG="# >>> envguard >>>"
ENVGUARD_RC_UNTAG="# <<< envguard <<<"

# --- Colors (if terminal supports it) ---
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
    local shell_name=""
    if [ -n "${ZSH_VERSION:-}" ]; then
        shell_name="zsh"
    elif [ -n "${BASH_VERSION:-}" ]; then
        shell_name="bash"
    elif [ -n "${FISH_VERSION:-}" ]; then
        shell_name="fish"
    else
        shell_name="unknown"
    fi
    echo "$shell_name"
}

# --- Determine RC file path ---
get_rc_path() {
    local shell_type="$1"
    local home_dir
    home_dir="$(cd ~ && pwd)"

    case "$shell_type" in
        zsh)
            # Prefer .zshrc, fall back to .zprofile
            if [ -f "${home_dir}/.zshrc" ]; then
                echo "${home_dir}/.zshrc"
            else
                echo "${home_dir}/.zprofile"
            fi
            ;;
        bash)
            # On macOS, interactive shells use .bash_profile; on Linux, .bashrc
            if [[ "$(uname)" == "Darwin" ]]; then
                if [ -f "${home_dir}/.bash_profile" ]; then
                    echo "${home_dir}/.bash_profile"
                else
                    echo "${home_dir}/.bashrc"
                fi
            else
                echo "${home_dir}/.bashrc"
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

# --- Check if hooks are already installed ---
hooks_installed() {
    local rc_path="$1"
    if [ ! -f "$rc_path" ]; then
        return 1  # File doesn't exist, not installed
    fi
    grep -qF "$ENVGUARD_RC_TAG" "$rc_path" 2>/dev/null && return 0 || return 1
}

# --- Install hooks for bash/zsh ---
install_posix_hooks() {
    local rc_path="$1"
    local hook_block

    hook_block=$(cat <<'HOOK_EOF'

# >>> envguard >>>
# envguard shell integration - managed by envguard
# Run `envguard uninstall-shell-hooks` to remove
_envguard_hook() {
    if command -v envguard &>/dev/null; then
        eval "$(envguard shell-hook 2>/dev/null)" || true
    fi
}
if [[ -z "${ENVGUARD_DISABLED:-}" ]]; then
    _envguard_hook
    unset -f _envguard_hook
fi
# <<< envguard <<<
HOOK_EOF
)

    # Ensure the RC file exists
    touch "$rc_path"

    # Check for existing installation
    if hooks_installed "$rc_path"; then
        warn "envguard hooks already installed in $rc_path"
        warn "Run 'envguard uninstall-shell-hooks' first, or edit manually."
        return 0
    fi

    # Append the hook block
    echo "" >> "$rc_path"
    echo "$hook_block" >> "$rc_path"

    info "Installed envguard hooks in ${BLUE}$rc_path${NC}"
    info "Restart your shell or run: source $rc_path"
}

# --- Install hooks for fish ---
install_fish_hooks() {
    local rc_path="$1"

    # Ensure directory exists
    mkdir -p "$(dirname "$rc_path")"

    if hooks_installed "$rc_path"; then
        warn "envguard hooks already installed in $rc_path"
        return 0
    fi

    cat >> "$rc_path" <<'FISH_EOF'

# >>> envguard >>>
# envguard shell integration - managed by envguard
if command -v envguard &>/dev/null; and not set -q ENVGUARD_DISABLED
    envguard shell-hook 2>/dev/null | source
end
# <<< envguard <<<
FISH_EOF

    info "Installed envguard hooks in ${BLUE}$rc_path${NC}"
}

# --- Try Python module first (preferred method) ---
install_via_python() {
    info "Attempting installation via Python module..."

    if command -v envguard &>/dev/null; then
        if envguard install-shell-hooks "$@"; then
            info "Hooks installed via envguard Python module."
            return 0
        else
            warn "Python module installation failed, falling back to shell script."
            return 1
        fi
    else
        warn "envguard command not found, using shell script method."
        return 1
    fi
}

# --- Main ---
main() {
    local shell_type="${1:-$(detect_shell)}"
    local rc_path

    echo -e "${BOLD}envguard - Install Shell Hooks${NC}"
    echo ""

    # Validate shell type
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
    if install_via_python "$shell_type"; then
        return 0
    fi

    # Fall back to shell script
    rc_path="$(get_rc_path "$shell_type")"
    info "RC file: ${BLUE}$rc_path${NC}"

    case "$shell_type" in
        zsh|bash)
            install_posix_hooks "$rc_path"
            ;;
        fish)
            install_fish_hooks "$rc_path"
            ;;
    esac

    info ""
    info "${GREEN}Done!${NC} Restart your shell for changes to take effect."
}

main "$@"
