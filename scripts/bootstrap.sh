#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.
#
# bootstrap.sh - Initial bootstrap script for a fresh macOS install
#
# This script automates setting up a complete envguard development
# environment on a fresh macOS machine. It checks prerequisites,
# installs envguard in development mode, configures shell hooks,
# installs the update LaunchAgent, and runs the doctor diagnostic.

set -euo pipefail

# --- Configuration ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MIN_PYTHON_VERSION="3.10"

# --- Colors ---
if [[ -t 1 ]] && command -v tput &>/dev/null && [[ $(tput colors 2>/dev/null || echo 0) -ge 8 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    DIM='\033[2m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' DIM='' NC=''
fi

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step()  { echo -e "\n${BOLD}${BLUE}==>${NC} ${BOLD}$*${NC}"; }

# --- Helper: compare versions ---
version_gte() {
    # Returns 0 if $1 >= $2
    local v1="$1" v2="$2"
    [ "$(printf '%s\n' "$v2" "$v1" | sort -V | head -n1)" = "$v2" ]
}

# --- Step 1: Check platform ---
check_platform() {
    step "Checking platform..."

    if [[ "$(uname)" != "Darwin" ]]; then
        warn "This bootstrap script is designed for macOS."
        warn "Current platform: $(uname -s)"
        warn "Continuing anyway, but some features may not work."
    else
        local macos_version
        macos_version="$(sw_vers -productVersion 2>/dev/null || echo "unknown")"
        local arch
        arch="$(uname -m)"
        info "macOS ${macos_version} (${arch})"
    fi
}

# --- Step 2: Check Python ---
check_python() {
    step "Checking Python installation..."

    local python_bin=""

    # Search for Python 3
    for cmd in python3 python3.12 python3.11 python3.10; do
        if command -v "$cmd" &>/dev/null; then
            python_bin="$(command -v "$cmd")"
            break
        fi
    done

    if [ -z "$python_bin" ]; then
        error "Python 3 not found!"
        echo ""
        echo "Install Python 3.10+ using one of:"
        echo "  1. Homebrew:  brew install python@3.11"
        echo "  2. pyenv:     pyenv install 3.11 && pyenv global 3.11"
        echo "  3. Official:  https://www.python.org/downloads/"
        exit 1
    fi

    # Check version
    local py_version
    py_version="$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    local py_major_minor
    py_major_minor="$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

    info "Found Python: ${BLUE}${python_bin}${NC} (${py_version})"

    if ! version_gte "$py_major_minor" "$MIN_PYTHON_VERSION"; then
        error "Python ${py_version} is too old. Minimum required: ${MIN_PYTHON_VERSION}"
        echo ""
        echo "Upgrade Python using one of:"
        echo "  1. Homebrew:  brew install python@3.11"
        echo "  2. pyenv:     pyenv install 3.11 && pyenv global 3.11"
        exit 1
    fi

    # Check pip
    if ! "$python_bin" -m pip --version &>/dev/null; then
        warn "pip not found for ${python_bin}."
        info "Installing pip via ensurepip..."
        if ! "$python_bin" -m ensurepip --upgrade 2>/dev/null; then
            error "ensurepip failed. Install pip manually: $python_bin -m pip install --upgrade pip"
            exit 1
        fi
    fi

    echo "$python_bin"
}

# --- Step 3: Check for Xcode Command Line Tools ---
check_xcode_tools() {
    step "Checking Xcode Command Line Tools..."

    if [[ "$(uname)" != "Darwin" ]]; then
        info "Skipping Xcode check (not macOS)."
        return
    fi

    if xcode-select -p &>/dev/null; then
        info "Xcode Command Line Tools: ${GREEN}installed${NC}"
    else
        warn "Xcode Command Line Tools not found."
        echo ""
        if [[ "$ENVGUARD_YES" -eq 1 ]]; then
            REPLY="y"
        else
            read -p "Install Xcode Command Line Tools now? [Y/n] " -n 1 -r
            echo ""
        fi
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            info "Installing Xcode Command Line Tools..."
            xcode-select --install
            warn "Xcode CLT installation started."
            warn "You may need to run this script again after installation completes."
            exit 0
        else
            warn "Xcode CLT is recommended for building Python extensions."
        fi
    fi
}

# --- Step 4: Create virtual environment ---
create_venv() {
    step "Setting up virtual environment..."

    local python_bin="$1"
    local venv_dir="${PROJECT_ROOT}/.venv"

    if [ -d "$venv_dir" ]; then
        if [ -f "${venv_dir}/bin/activate" ]; then
            info "Virtual environment already exists: ${BLUE}${venv_dir}${NC}"
            read -p "Recreate it? [y/N] " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -rf "$venv_dir"
            else
                echo "$venv_dir"
                return
            fi
        else
            warn "Corrupted venv found. Recreating..."
            rm -rf "$venv_dir"
        fi
    fi

    "$python_bin" -m venv "$venv_dir"
    info "Created virtual environment: ${BLUE}${venv_dir}${NC}"
    echo "$venv_dir"
}

# --- Step 5: Install envguard in development mode ---
install_envguard() {
    step "Installing envguard in development mode..."

    local venv_dir="$1"

    # Activate venv
    source "${venv_dir}/bin/activate"

    # Upgrade pip
    info "Upgrading pip..."
    pip install --upgrade pip 2>&1 | tail -1

    # Install in development mode with dev dependencies
    info "Installing envguard..."
    if [ -f "${PROJECT_ROOT}/pyproject.toml" ]; then
        pip install -e "${PROJECT_ROOT}[dev]" 2>&1 | tail -3
    else
        pip install -e "${PROJECT_ROOT}" 2>&1 | tail -3
    fi

    # Verify installation
    if command -v envguard &>/dev/null; then
        local eg_version
        eg_version="$(envguard --version 2>/dev/null || echo "unknown")"
        info "envguard installed: ${GREEN}${eg_version}${NC}"
    else
        warn "envguard command not found after installation."
        warn "You may need to activate the venv manually:"
        warn "  source ${venv_dir}/bin/activate"
    fi

    # Deactivate
    deactivate 2>/dev/null || true
}

# --- Step 6: Set up shell hooks ---
setup_shell_hooks() {
    step "Setting up shell integration..."

    local shell_type=""
    if [ -n "${ZSH_VERSION:-}" ]; then
        shell_type="zsh"
    elif [ -n "${BASH_VERSION:-}" ]; then
        shell_type="bash"
    else
        shell_type="unknown"
    fi

    if [ "$shell_type" = "unknown" ]; then
        warn "Could not detect shell. Skipping hook installation."
        warn "Run manually: ./scripts/install-shell-hooks.sh"
        return
    fi

    echo ""
    if [[ "$ENVGUARD_YES" -eq 1 ]]; then
        REPLY="y"
    else
        read -p "Install envguard shell hooks for ${shell_type}? [Y/n] " -n 1 -r
        echo ""
    fi
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        "${SCRIPT_DIR}/install-shell-hooks.sh" "$shell_type"
    else
        info "Skipped shell hooks. Run later: ./scripts/install-shell-hooks.sh"
    fi
}

# --- Step 7: Install LaunchAgent ---
setup_launch_agent() {
    step "Setting up auto-update LaunchAgent..."

    if [[ "$(uname)" != "Darwin" ]]; then
        info "Skipping LaunchAgent (not macOS)."
        return
    fi

    echo ""
    if [[ "$ENVGUARD_YES" -eq 1 ]]; then
        REPLY="y"
    else
        read -p "Install envguard LaunchAgent for auto-updates? [Y/n] " -n 1 -r
        echo ""
    fi
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        "${SCRIPT_DIR}/install-launch-agent.sh"
    else
        info "Skipped LaunchAgent. Run later: ./scripts/install-launch-agent.sh"
    fi
}

# --- Step 8: Run doctor ---
run_doctor() {
    step "Running envguard doctor..."

    local venv_dir="$1"

    if [ -f "${venv_dir}/bin/envguard" ]; then
        "${venv_dir}/bin/envguard" doctor 2>/dev/null || \
            "${venv_dir}/bin/envguard" doctor
    elif command -v envguard &>/dev/null; then
        envguard doctor 2>/dev/null || envguard doctor
    else
        warn "envguard not found. Activate the venv first:"
        warn "  source ${venv_dir}/bin/activate"
        warn "  envguard doctor"
        return
    fi
}

# --- Final summary ---
print_summary() {
    local venv_dir="$1"

    echo ""
    echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}  envguard bootstrap complete!${NC}"
    echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${DIM}Virtual environment:${NC} ${venv_dir}"
    echo -e "  ${DIM}Activate:${NC}           source ${venv_dir}/bin/activate"
    echo -e "  ${DIM}Verify:${NC}             envguard doctor"
    echo -e "  ${DIM}Quick start:${NC}        envguard init && envguard run python -c 'import sys; print(sys.version)'"
    echo ""
    echo -e "  ${DIM}Documentation:${NC}      See docs/ directory"
    echo -e "  ${DIM}Examples:${NC}           See examples/ directory"
    echo ""
}

# Global non-interactive flag (set by --yes / -y)
ENVGUARD_YES=0

# --- Main ---
main() {
    echo -e "${BOLD}${BLUE}╔════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${BLUE}║   envguard - macOS Bootstrap          ║${NC}"
    echo -e "${BOLD}${BLUE}║   Environment Setup Script             ║${NC}"
    echo -e "${BOLD}${BLUE}╚════════════════════════════════════════╝${NC}"
    echo -e "${DIM}Project root: ${PROJECT_ROOT}${NC}"
    echo ""

    # Check for --help
    if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Bootstrap a fresh macOS environment for envguard development."
        echo ""
        echo "Steps:"
        echo "  1. Check platform (macOS)"
        echo "  2. Verify Python 3.10+"
        echo "  3. Check Xcode Command Line Tools"
        echo "  4. Create virtual environment"
        echo "  5. Install envguard in dev mode"
        echo "  6. Set up shell hooks (optional)"
        echo "  7. Install LaunchAgent (optional, macOS only)"
        echo "  8. Run envguard doctor"
        echo ""
        echo "Options:"
        echo "  --help, -h    Show this help message"
        echo "  --yes, -y     Accept all prompts (non-interactive)"
        exit 0
    fi

    # Parse flags
    for arg in "$@"; do
        case "$arg" in
            --yes|-y) ENVGUARD_YES=1 ;;
        esac
    done

    check_platform
    local python_bin
    python_bin="$(check_python)"
    check_xcode_tools
    local venv_dir
    venv_dir="$(create_venv "$python_bin")"
    install_envguard "$venv_dir"
    setup_shell_hooks
    setup_launch_agent
    run_doctor "$venv_dir"
    print_summary "$venv_dir"
}

main "$@"
