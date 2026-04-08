# envguard

**macOS-first Python environment orchestration framework**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-informational.svg)](#platform-support)
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-orange.svg)]()
[![GitHub](https://img.shields.io/badge/GitHub-rotsl%2Fenvguard-black.svg)](https://github.com/rotsl/envguard)

> **Copyright &copy; 2026 Rohan R. Licensed under the Apache License, Version 2.0.**
>
> **Repository:** [https://github.com/rotsl/envguard](https://github.com/rotsl/envguard)

---

## Table of Contents

1. [What is envguard?](#what-is-envguard)
2. [Platform Support](#platform-support)
3. [Quick Start](#quick-start)
4. [Installation](#installation)
    - [macOS](#installation--macos)
    - [Linux](#installation--linux)
    - [Windows](#installation--windows)
    - [From source (dev venv)](#installation--from-source-dev-venv)
5. [Core Concepts](#core-concepts)
6. [The Preflight Pipeline](#the-preflight-pipeline)
7. [All Commands](#all-commands)
8. [Configuration](#configuration)
9. [Rules Engine](#rules-engine)
10. [GPU Acceleration](#gpu-acceleration)
11. [Shell Integration](#shell-integration)
12. [LaunchAgent (macOS)](#launchagent-macos)
13. [Self-Updating & Rollback](#self-updating--rollback)
14. [Security Model](#security-model)
15. [Snapshots & State](#snapshots--state)
16. [Exit Codes](#exit-codes)
17. [JSON Output Mode](#json-output-mode)
18. [Repair System](#repair-system)
19. [Project Structure](#project-structure)
20. [Architecture](#architecture)
21. [Development Workflow](#development-workflow)
22. [Contributing](#contributing)
23. [Limitations](#limitations)
24. [License](#license)

---

## What is envguard?

envguard is a CLI tool that **detects, validates, and orchestrates Python environments**. It inspects your project, your host system, and your dependencies to catch problems *before* you run your code — not after a cryptic traceback.

Instead of `python train.py` (and hoping for the best), you run `envguard run -- python train.py`. Before your code executes, envguard runs a **preflight pipeline** that verifies:

- Platform compatibility and macOS version
- Python architecture (arm64 vs x86_64, Rosetta 2 detection)
- Package manager health and version correctness
- Dependency conflicts and wheel compatibility
- GPU accelerator availability (MPS on Apple Silicon, CUDA incompatibility on macOS)
- Environment integrity and permissions

If anything is wrong, execution is **blocked** with a clear, actionable error message. If everything passes, your command runs in the validated environment.

### Core capabilities

| Capability | Description |
|---|---|
| **Host detection** | macOS version, architecture (Apple Silicon / Intel / Rosetta 2), Python, package managers (pip/conda/mamba/uv/pipx/poetry), Xcode CLI, network |
| **Project discovery** | Scans `pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile`, `environment.yml`, `poetry.lock`, `.python-version`, wheelhouse dirs |
| **Intent analysis** | Infers environment type (venv/conda/pipenv/poetry), Python version, accelerator targets (CPU/MPS/CUDA) |
| **Rules engine** | 15+ preflight rules: platform, architecture, Python version, CUDA detection, MPS, Rosetta, wheels, pip/conda ownership, permissions, network |
| **Automated repair** | Recreate environments, fix mixed pip/conda ownership, switch Python versions, rebuild native extensions |
| **Managed execution** | Every `envguard run` is preceded by the full preflight pipeline |
| **Shell integration** | Optional zsh/bash hooks |
| **Self-updating** | Verified updates with SHA-256 checksum and rollback support |
| **LaunchAgent** | macOS periodic update checker (macOS only) |

### What envguard does NOT guarantee

| Limitation | Explanation |
|---|---|
| **Does NOT intercept unmanaged launches** | Only entry points routed through `envguard run` are validated. IDE run buttons, direct `python`, cron jobs are not checked. |
| **Only protects managed entry points** | The safety net activates only with `envguard run -- <cmd>` or `envguard preflight`. |
| **Cannot force internet access** | Detects and warns about network issues; cannot fix them. |
| **Cannot bypass OS permissions** | Reports Gatekeeper/SIP failures; cannot override them. |
| **Cannot make CUDA work on macOS** | Hardware constraint — no workaround exists. Detected and flagged as CRITICAL. |
| **macOS-primary** | Full feature set on macOS only. Linux: core pipeline works. Windows: not supported. |

---

## Platform Support

| Platform | Support level | Notes |
|---|---|---|
| **macOS 12 (Monterey)+** | **Full** | Primary target. All features available. |
| **macOS 11 (Big Sur)** | Partial | Works but below minimum version recommendation. |
| **Linux (Ubuntu, Debian, Fedora, Arch)** | Partial | Core pipeline, Doctor, Repair, Update work. LaunchAgent, MPS, Rosetta checks skip gracefully. |
| **Windows** | **Not supported** | No plans for Windows support. POSIX APIs are used throughout. |

### macOS-specific features (not available on Linux/Windows)

- `install-launch-agent` / `uninstall-launch-agent` — macOS `launchd` only
- `accelerator_support` doctor check — MPS (Metal Performance Shaders) — Apple Silicon only
- Rosetta 2 detection (`ROSETTA_TRANSLATION_DETECTED` rule)
- Xcode Command Line Tools check (`xcode-select`)
- `~/Library/LaunchAgents/` plist management

---

## Quick Start

```bash
# Install
pip install envguard

# Initialize your project
cd /path/to/your/project
envguard init

# Run with preflight
envguard run -- pytest -v
envguard run -- python train.py
envguard run -- jupyter lab
```

---

## Installation

### Installation — macOS

**Requirements:**

- macOS 12.0 (Monterey) or later
- Python 3.10+
- Xcode Command Line Tools (recommended): `xcode-select --install`

```bash
# Option 1: pip (PyPI)
pip install envguard

# Option 2: with Homebrew Python
brew install python@3.12
python3 -m pip install envguard

# Option 3: with pyenv
pyenv install 3.12.0
pyenv global 3.12.0
pip install envguard

# Verify
envguard --version
envguard doctor
```

**Apple Silicon (M1/M2/M3/M4) — important:**

Use a **native arm64 Python**. Running x86_64 Python under Rosetta 2 is detected and flagged as a `ROSETTA_TRANSLATION_DETECTED` warning. Confirm your Python architecture:

```bash
python3 -c "import platform; print(platform.machine())"
# Should output: arm64
```

If it says `x86_64`, install a native arm64 Python:

```bash
brew install python@3.12       # Homebrew installs native arm64 on Apple Silicon
# or
arch -arm64 pyenv install 3.12.0
```

**Bootstrap script (installs everything including shell hooks and LaunchAgent):**

```bash
cd /path/to/envguard-repo
bash scripts/bootstrap.sh        # interactive
bash scripts/bootstrap.sh --yes  # non-interactive (accept all prompts)
```

---

### Installation — Linux

```bash
# Ubuntu / Debian
sudo apt-get install python3 python3-pip python3-venv
pip install envguard

# Fedora / RHEL
sudo dnf install python3 python3-pip
pip install envguard

# Arch Linux
sudo pacman -S python python-pip
pip install envguard

# Verify
envguard --version
envguard doctor
```

**Notes for Linux:**

- LaunchAgent (`install-launch-agent`) is not available — use systemd timers or cron for periodic update checks.
- MPS (Metal Performance Shaders) is macOS-only. The `accelerator_support` check will be skipped.
- Xcode CLI tools check is skipped.
- The core preflight pipeline (host detection, Python checks, permissions, rules, repair) works fully on Linux.

**Systemd timer alternative for Linux auto-updates:**

```ini
# ~/.config/systemd/user/envguard-update.service
[Unit]
Description=envguard update check

[Service]
ExecStart=/usr/local/bin/envguard update --dry-run
```

```ini
# ~/.config/systemd/user/envguard-update.timer
[Unit]
Description=envguard daily update check

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now envguard-update.timer
```

---

### Installation — Windows

**Windows is not supported.** envguard uses POSIX-specific APIs throughout its codebase:

- `os.access()` for permission checking
- `subprocess` with list-form arguments (POSIX convention)
- `/tmp` paths
- `~/Library/LaunchAgents/` (macOS-specific)
- `xcode-select` detection
- `platform.mac_ver()` for version detection

There are no plans to add Windows support in the current roadmap. For Windows environments, consider:

- [WSL2](https://learn.microsoft.com/en-us/windows/wsl/) (Windows Subsystem for Linux) — envguard works under WSL2 with Linux support level
- [pyenv-win](https://github.com/pyenv-win/pyenv-win) + manual venv management

---

### Installation — From source (dev venv)

The recommended way to develop or test envguard from source uses the **`guardenv`** venv:

```bash
# Clone
git clone https://github.com/rotsl/envguard.git
cd envguard

# Option A: Makefile (recommended)
make install-guardenv

# Option B: manual
python3 -m venv guardenv
guardenv/bin/pip install -e ".[dev]"

# Verify
guardenv/bin/envguard --help
guardenv/bin/envguard doctor

# Activate (optional)
source guardenv/bin/activate
envguard --help
```

This installs envguard in editable mode with all dev dependencies (`pytest`, `mypy`, `ruff`, `pytest-cov`, `pytest-mock`). The `guardenv/` directory is gitignored.

---

## Core Concepts

### Managed execution

`envguard run -- <command>` is the central interaction pattern. Every managed run:

1. Runs the full preflight pipeline
2. Blocks execution if any CRITICAL finding is detected
3. Activates the environment (prepends `ENV/bin` to `PATH`, sets `VIRTUAL_ENV` or `CONDA_PREFIX`)
4. Executes the command in the project directory
5. Returns the command's exit code

```bash
# Without envguard (no validation):
python train.py           # Might fail silently, wrong Python, wrong packages

# With envguard (validated):
envguard run -- python train.py  # Preflight → validates everything → runs safely
```

### The `.envguard/` directory

Every initialized project gets a `.envguard/` directory:

```
.envguard/
├── state.json       # Project metadata: env type, Python version, platform, timestamps
├── resolution.json  # Latest resolution record from preflight
├── envguard.toml    # Project-specific config overrides
├── envguard.lock    # Lock file (future: concurrent access prevention)
├── snapshots/       # Environment freeze snapshots (timestamped JSON)
├── cache/           # Downloaded manifests, wheel caches
├── logs/            # envguard log files
└── backups/         # Backups created before repair operations
```

All state files are written **atomically** (write to `.tmp`, then `os.rename()`) to prevent corruption from interrupted writes.

---

## The Preflight Pipeline

`PreflightEngine.run()` executes these 9 steps in sequence before any managed command:

| Step | Action | Output | Fails if |
| --- | --- | --- | --- |
| 1 | **Detect host** | `HostFacts` | Detector unavailable |
| 2 | **Discover project** | `ProjectIntent` | No readable project dir |
| 3 | **Analyze intent** | Updated `ProjectIntent` | — |
| 4 | **Evaluate rules** | `RuleFinding[]` | — (all rules always run) |
| 5 | **Fail-fast** | Block or continue | Any CRITICAL rule fires |
| 6 | **Create resolution** | `ResolutionRecord` | Cannot determine env |
| 7 | **Create/repair env** | Updated env | Environment creation fails |
| 8 | **Validate env** | `env_valid` bool | Python binary missing |
| 9 | **Smoke test** | `smoke_test_results` | Key import fails |

All findings are collected regardless of severity — only CRITICAL findings block execution.

---

## All Commands

| Command | Description | macOS | Linux |
|---|---|---|---|
| `envguard init [DIR]` | Initialize envguard for a project | ✓ | ✓ |
| `envguard doctor [DIR]` | Run all 10 diagnostic checks | ✓ | ✓ |
| `envguard detect [DIR]` | Detect and display host/project info | ✓ | ✓ |
| `envguard preflight [DIR]` | Run preflight checks without executing a command | ✓ | ✓ |
| `envguard run -- <CMD...>` | Run a command with preflight | ✓ | ✓ |
| `envguard repair [DIR]` | Repair the managed environment | ✓ | ✓ |
| `envguard freeze [DIR]` | Snapshot the current environment state | ✓ | ✓ |
| `envguard health [DIR]` | Display environment health status | ✓ | ✓ |
| `envguard status [DIR]` | Display envguard and environment status | ✓ | ✓ |
| `envguard update [--dry-run]` | Check for and apply envguard updates | ✓ | ✓ |
| `envguard rollback [SNAPSHOT_ID]` | Rollback to a previous snapshot | ✓ | ✓ |
| `envguard shell-hook` | Output shell integration code for `eval` | ✓ | ✓ |
| `envguard install-shell-hooks` | Install shell integration hooks | ✓ | ✓ |
| `envguard uninstall-shell-hooks` | Remove shell integration hooks | ✓ | ✓ |
| `envguard install-launch-agent` | Install macOS LaunchAgent for auto-updates | ✓ | — |
| `envguard uninstall-launch-agent` | Remove macOS LaunchAgent | ✓ | — |

All commands support `--json` / `-j` for machine-readable output.

### Global options

```bash
envguard --help                  # Show help
envguard --version               # Show version
envguard <command> --json        # Machine-readable JSON output
envguard <command> --help        # Command-specific help
```

### Command examples

```bash
# Initialize with specific Python and env type
envguard init --python 3.12 --env-type venv

# Run pytest with preflight, in a specific dir
envguard run --dir /path/to/project -- pytest -v

# Skip preflight when you know it's safe
envguard run --no-preflight -- python script.py

# Check for updates without installing
envguard update --dry-run

# Update on a specific channel
envguard update --channel stable

# Rollback to a specific snapshot
envguard rollback 20260401T120000-abc123

# JSON output (for CI, scripting, monitoring)
envguard doctor --json | jq '.checks[] | select(.status == "error")'
envguard status --json
```

---

## Configuration

envguard reads configuration from two sources, with project-level overriding global:

1. **Global**: `config/default.toml` in the envguard installation directory
2. **Project**: `.envguard/envguard.toml` in your project directory

Full configuration reference:

```toml
[general]
auto_preflight = true         # Run preflight before every managed command
log_level = "INFO"            # DEBUG, INFO, WARNING, ERROR
report_format = "text"        # text, json

[preflight]
check_network = true          # Check PyPI reachability
check_permissions = true      # Check filesystem permissions
check_python = true           # Check Python version and architecture
check_dependencies = true     # Check dependency compatibility
check_accelerator = true      # Check GPU accelerator (MPS/CUDA)
smoke_test_imports = true     # Test key imports in subprocess isolation
fail_on_unsupported = true    # Block on CRITICAL findings

[update]
channel = "stable"            # stable | beta | off
auto_check = true             # Background update checks
check_interval_hours = 24     # How often to check

[environment]
default_python_version = "3.11"
prefer_conda = false
venv_strategy = "isolated"    # isolated | shared

[repair]
auto_repair = false           # Repair automatically without prompting
max_repair_attempts = 3
backup_before_repair = true   # Always create a backup before repair

[accelerator]
supported_targets = ["cpu", "mps"]   # cpu | mps | cuda
reject_cuda_on_macos = true          # Always block CUDA on macOS
```

Set `channel = "off"` to disable all network update requests.

---

## Rules Engine

The rules engine evaluates 15+ preflight rules in sequence. All rules run regardless of findings (no short-circuit), so you always get a complete picture.

| Rule ID | Severity | What it checks |
|---|---|---|
| `PLATFORM_UNSUPPORTED` | CRITICAL | OS is not macOS or Linux |
| `CUDA_ON_MACOS` | CRITICAL | CUDA dependency detected on macOS |
| `ARCHITECTURE_MISMATCH` | ERROR | Python arch doesn't match project requirements |
| `PYTHON_VERSION_BELOW_MINIMUM` | ERROR | Python version below `requires-python` |
| `BROKEN_ENVIRONMENT` | ERROR | Active venv/conda is missing Python binary |
| `ROSETTA_TRANSLATION_DETECTED` | WARNING | x86_64 Python running under Rosetta 2 (macOS) |
| `WHEEL_INCOMPATIBLE` | WARNING | Wheel file doesn't match current platform/arch |
| `MIXED_PIP_CONDA_OWNERSHIP` | WARNING | Packages installed by both pip and conda |
| `SOURCE_BUILD_PREREQUISITES_MISSING` | WARNING | C/Fortran compiler not found for packages needing build |
| `NETWORK_UNAVAILABLE` | WARNING | Cannot reach PyPI (needed for installs/updates) |
| `ENVIRONMENT_NOT_FOUND` | WARNING | No venv or conda environment detected |
| `MPS_NOT_AVAILABLE` | INFO | Apple Silicon present but MPS not available |
| `DEPENDENCY_CONFLICT` | WARNING | Incompatible version constraints between packages |
| `STALE_ENVIRONMENT` | INFO | Environment not updated in >30 days |
| `PACKAGE_MANAGER_MISSING` | WARNING | pip/conda not found |

Each finding includes: `rule_id`, `severity`, `message`, `details` dict, `remediation` string, `auto_repairable` flag.

---

## GPU Acceleration

### macOS GPU model

| Target | Status | Notes |
|---|---|---|
| **CPU** | ✓ Full | Always available |
| **Apple MPS** | ✓ Supported | macOS 12.3+ on Apple Silicon. Used by PyTorch, mlx, some JAX backends. |
| **CUDA** | ✗ **Not supported** | Apple Silicon hardware cannot run NVIDIA CUDA. envguard flags any CUDA dependency as CRITICAL. |

envguard detects CUDA requirements from:

- `torch==2.x.x+cu118` style version strings
- `nvidia-*` package names
- `accelerator_target = "cuda"` in config

If detected on macOS, preflight is **blocked** with a CRITICAL finding and a suggestion to switch to `mps` or `cpu`.

```bash
# Check MPS availability
envguard doctor | grep accelerator

# JSON
envguard doctor --json | jq '.checks[] | select(.name == "accelerator_support")'
```

### MPS framework support

| Framework | MPS | Notes |
|---|---|---|
| PyTorch | ✓ | `torch.backends.mps.is_available()` |
| mlx | ✓ | Apple's own ML framework |
| TensorFlow | Partial | Requires `tensorflow-metal` plugin |
| JAX | Partial | Experimental MPS backend |
| NumPy/SciPy | ✗ | CPU-only |

### Linux GPU model

On Linux, envguard does not restrict CUDA. The `accelerator_support` check is skipped on Linux. CUDA usage on Linux is out of scope for envguard's rules.

---

## Shell Integration

Shell hooks are **opt-in** and never installed automatically.

```bash
# Install (zsh or bash, auto-detected)
envguard install-shell-hooks

# Install for a specific shell
envguard install-shell-hooks --shell zsh
envguard install-shell-hooks --shell bash

# Uninstall
envguard uninstall-shell-hooks

# The installed block looks like:
# >>> envguard >>>
# envguard shell integration - managed by envguard
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
```

Set `ENVGUARD_DISABLED=1` in your environment to suppress the hook for a session.

Shell hooks **do not**:

- Automatically activate environments on directory change (use `direnv` for that)
- Provide command completion
- Support fish, tcsh, ksh
- Modify your shell prompt

---

## LaunchAgent (macOS)

The macOS LaunchAgent runs `envguard update --dry-run` on a schedule and notifies you when an update is available.

```bash
# Install (creates ~/Library/LaunchAgents/com.envguard.update.plist)
envguard install-launch-agent

# Uninstall
envguard uninstall-launch-agent

# Check status
envguard status --json | jq '.launch_agent'
```

The plist runs daily (configurable via `check_interval_hours` in config). Logs are written to `~/.envguard/logs/update-stdout.log` and `~/.envguard/logs/update-stderr.log`.

The LaunchAgent **only checks for updates**. It does not intercept processes, modify environments, or require elevated permissions.

**Linux alternative:** Use a systemd timer — see [Installation — Linux](#installation--linux).

---

## Self-Updating & Rollback

```bash
# Check for updates (no changes)
envguard update --dry-run

# Check and apply update
envguard update

# List available rollback snapshots
envguard rollback

# Rollback to a specific snapshot
envguard rollback <snapshot-id>
```

### Update pipeline

1. Fetch remote manifest from `https://releases.envguard.dev/manifest.json` (HTTPS)
2. Compare versions using `packaging.version.Version`
3. Download update archive
4. Verify SHA-256 checksum against manifest
5. Validate platform compatibility
6. Create rollback snapshot (before applying)
7. Extract archive to staging directory (with zip-slip protection)
8. Copy files to installation directory (with path traversal protection)
9. Report success

### Rollback

A rollback snapshot is created automatically before every update. Snapshots are stored at `~/.envguard/snapshots/`. Rollback restores the previous envguard package files.

---

## Security Model

envguard's security model is documented in detail in [docs/threat-model.md](docs/threat-model.md). Key points:

### Trust boundaries

```
Untrusted:   Remote manifest server · PyPI · Project dependencies · Downloaded archives
Semi-trusted: Shell RC files · LaunchAgent plists · Project config · Wheel archives
Trusted:      envguard codebase · Python runtime · macOS/Linux system APIs
```

### Security mitigations

| Attack surface | Mitigation |
|---|---|
| **Zip/tar path traversal (zip-slip)** | Every archive member is validated against the staging directory before extraction |
| **Update integrity bypass** | Missing checksums in manifests **fail closed** (blocked, not bypassed) |
| **Command injection** | All subprocess calls use list-form arguments — never `shell=True` with string interpolation |
| **Shell RC injection** | Installed hook block is a fixed snippet; no dynamic content |
| **State file corruption** | Atomic writes (`write .tmp → os.rename`) for all JSON state files |
| **VIRTUAL_ENV spoofing** | `detect_active_env()` validates Python binary exists inside the reported path |
| **Rollback** | Snapshot created before every update; `RollbackManager.rollback()` restores previous state |
| **Subprocess timeouts** | Every subprocess call has an explicit timeout (5–3600 seconds) |
| **User-level only** | Never writes to system directories. LaunchAgent goes to `~/Library/LaunchAgents/`, not `/Library/` |

### Security limitations (known and accepted)

| Limitation | Details |
|---|---|
| **Checksum-only verification** | No GPG signature, no Apple code signing, no certificate pinning. A correctly-checksummed malicious update would bypass verification. |
| **No TLS certificate pinning** | Uses system's default certificate chain. A compromised CA could MITM the update channel. |
| **No sandboxing** | Runs with user's full permissions. |
| **No secret management** | Environment variables are passed through as-is. |
| **No integrity monitoring** | Does not detect tampering of its own files between runs. |
| **Plain-text state files** | `.envguard/*.json` and snapshots are stored as plain JSON. |
| **No audit log to external systems** | Logs are local only. No syslog, SIEM, or tamper-proof audit trail. |

### Security recommendations

1. **Pin the version** — `pip install envguard==0.1.0` rather than `pip install envguard`
2. **Disable updates in locked environments** — set `channel = "off"` in config
3. **Review shell RC changes** — inspect `~/.zshrc` or `~/.bashrc` after `install-shell-hooks`
4. **Review the LaunchAgent plist** — inspect `~/Library/LaunchAgents/com.envguard.update.plist` after installation
5. **Do not run as root** — envguard is designed for user-level installations
6. **Keep Python patched** — envguard's security depends on a correctly patched Python runtime
7. **Audit freeze snapshots** — periodically inspect `.envguard/snapshots/` for unexpected changes

---

## Snapshots & State

```bash
# Capture the current environment as a snapshot
envguard freeze

# Capture to a specific file
envguard freeze --output requirements-frozen.json

# View status
envguard status

# List rollback snapshots
envguard rollback
```

Snapshots capture: `created_at`, `envguard_version`, `python_version`, `project_dir`, `project_type`, `active_env`, `packages` (pip freeze output), `package_count`, `platform`.

---

## Exit Codes

| Code | Constant | Meaning |
|---|---|---|
| `0` | `EXIT_OK` | Success |
| `1` | `EXIT_GENERAL_ERROR` | Unspecified error |
| `2` | `EXIT_PREFLIGHT_FAILED` | Preflight checks failed (critical finding) |
| `3` | `EXIT_ENV_NOT_FOUND` | Environment not found |
| `4` | `EXIT_ENV_CORRUPT` | Environment is corrupted |
| `5` | `EXIT_PERMISSION_DENIED` | Permission error |
| `6` | `EXIT_NETWORK_ERROR` | Network unavailable |
| `7` | `EXIT_UNSUPPORTED_PLATFORM` | Platform not supported |
| `8` | `EXIT_CONFIG_ERROR` | Configuration error |
| `10` | `EXIT_UPDATE_AVAILABLE` | Update is available |
| `11` | `EXIT_ALREADY_UP_TO_DATE` | Already at latest version |
| `12` | `EXIT_ROLLBACK_FAILED` | Rollback operation failed |

Exit code 9 is intentionally skipped to avoid confusion with the Unix `SIGKILL` convention.

---

## JSON Output Mode

Every command supports `--json` / `-j` for machine-readable output. Useful for CI/CD pipelines, monitoring, and scripting.

```bash
# Doctor results as JSON
envguard doctor --json

# Filter errors only
envguard doctor --json | jq '.checks[] | select(.status == "error")'

# Check if preflight passed
envguard preflight --json | jq '.passed'

# Get current version info
envguard update --dry-run --json | jq '{current, latest, update_available}'

# Status summary
envguard status --json
```

---

## Repair System

envguard can automatically repair broken environments:

```bash
# Attempt to repair the current project's environment
envguard repair

# JSON output
envguard repair --json
```

Repair operations (in order of application):

1. **Validate state** — recreate `state.json` if missing or corrupt
2. **Validate environment path** — check if the recorded env still exists
3. **Remove stale references** — update state if env was deleted
4. **Recreate environment** — if environment is missing or corrupt
5. **Fix mixed pip/conda ownership** — run `conda-unpack` or selective reinstall
6. **Switch Python version** — if environment uses wrong Python
7. **Update state metadata** — refresh platform info and timestamps

A backup is created before any destructive repair operation. Backups are stored at `.envguard/backups/`.

---

## Project Structure

```
envguard/
├── src/envguard/
│   ├── __init__.py          # Package metadata, exit codes, shared utilities
│   ├── __main__.py          # python -m envguard entry point
│   ├── cli.py               # Typer CLI — 16 commands
│   ├── models.py            # Data models: HostFacts, ProjectIntent, RuleFinding, PreflightResult, …
│   ├── exceptions.py        # 18 custom exception classes
│   ├── detect.py            # HostDetector — OS, arch, Python, shell, network, permissions
│   ├── doctor.py            # 10 diagnostic checks
│   ├── rules.py             # RulesEngine — 15+ preflight rules
│   ├── preflight.py         # PreflightEngine — 9-step pipeline orchestration
│   ├── repair.py            # RepairEngine — automated environment repair
│   ├── logging.py           # Structured logging via get_logger()
│   ├── project/
│   │   ├── discovery.py     # Project file scanning → ProjectIntent
│   │   ├── intent.py        # Intent analysis (accelerators, compatibility, recommendations)
│   │   ├── resolution.py    # ResolutionManager → ResolutionRecord
│   │   └── lifecycle.py     # Full lifecycle orchestration
│   ├── macos/
│   │   ├── permissions.py   # macOS permission checking (LaunchAgent, RC write, subprocess)
│   │   ├── paths.py         # macOS-specific paths
│   │   ├── rosetta.py       # Rosetta 2 detection (sysctl proc_translated)
│   │   ├── system_install.py
│   │   └── xcode.py         # Xcode CLI tools detection
│   ├── security/
│   │   ├── signatures.py    # SHA-256/384/512 hash computation
│   │   └── trust.py         # Trust boundary evaluation
│   ├── resolver/
│   │   ├── base.py          # Resolver interface
│   │   ├── conda_backend.py # conda resolution
│   │   ├── inference.py     # Environment inference
│   │   └── wheelcheck.py    # Wheel compatibility checks
│   ├── update/
│   │   ├── manifest.py      # Update manifest parsing and version comparison
│   │   ├── updater.py       # UpdateManager — fetch, verify, stage, apply
│   │   ├── verifier.py      # UpdateVerifier — SHA-256 checksum, platform, Python version
│   │   └── rollback.py      # RollbackManager — snapshot and restore
│   ├── launch/
│   │   ├── runner.py        # Managed subprocess execution
│   │   ├── shell_hooks.py   # zsh/bash RC file management
│   │   └── launch_agent.py  # macOS LaunchAgent plist management
│   └── reports/
│       ├── health.py        # Health report generation
│       └── json_report.py   # JSON report serialization
├── tests/
│   ├── conftest.py          # Shared fixtures: HostFacts, ProjectIntent, RuleFinding
│   ├── unit/                # 200+ unit tests
│   └── integration/         # 60+ integration tests
├── docs/
│   ├── architecture.md      # Module dependency diagram, pipeline stages, data flow
│   ├── command-reference.md # Full CLI reference
│   ├── contributing.md      # Contribution guidelines
│   ├── limitations.md       # Known limitations and edge cases
│   ├── macos-install.md     # macOS-specific installation guide
│   ├── permissions.md       # Permission model documentation
│   ├── threat-model.md      # Security threat model and mitigations
│   ├── troubleshooting.md   # Common issues and fixes
│   ├── update-model.md      # Update mechanism documentation
│   └── adrs/                # Architecture Decision Records
│       ├── 0001-macos-only-initial-version.md
│       ├── 0002-no-cuda-on-macos.md
│       ├── 0003-checksum-only-updates.md
│       └── 0004-managed-execution-model.md
├── config/
│   ├── default.toml         # Default configuration
│   └── example-manifest.json
├── scripts/
│   ├── bootstrap.sh         # Full environment bootstrap (supports --yes)
│   ├── install-shell-hooks.sh
│   ├── uninstall-shell-hooks.sh
│   ├── install-launch-agent.sh
│   └── uninstall-launch-agent.sh
├── examples/
│   ├── pip-simple/          # pip + pyproject.toml example
│   ├── conda-env/           # conda environment.yml example
│   ├── mps-intent/          # Apple Silicon MPS example
│   ├── cuda-unsupported/    # CUDA-on-macOS detection example
│   ├── pyproject-based/     # pyproject.toml example
│   ├── requirements-txt/    # requirements.txt example
│   └── broken-mixed/        # Intentionally broken pip/conda mix
├── launchd/
│   └── com.envguard.update.plist   # LaunchAgent plist template
├── pyproject.toml
├── Makefile
└── LICENSE
```

---

## Architecture

### Layered design

```
┌─────────────────────────────────────────────────────────┐
│                       CLI Layer                          │
│              cli.py (Typer, 16 commands)                 │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │     Orchestration Layer     │
         │  doctor.py · preflight.py  │
         └─────────────┬──────────────┘
                       │
   ┌───────────────────▼──────────────────────┐
   │              Domain Layer                 │
   │  detect · rules · repair · models         │
   │  project/ · resolver/ · update/           │
   └───────────────────┬──────────────────────┘
                       │
   ┌───────────────────▼──────────────────────┐
   │            Platform Layer                 │
   │     macos/ · security/ · launch/          │
   └───────────────────────────────────────────┘
```

### Error handling

All envguard errors inherit from `EnvguardError`:

```
EnvguardError
├── PlatformNotSupportedError
├── CudaNotSupportedOnMacosError
├── IncompatibleWheelError
├── DependencyConflictError
├── BrokenEnvironmentError
├── EnvironmentCreationError
├── RepairError
├── PreflightError
├── NetworkUnavailableError
├── PackageManagerNotFoundError
├── ArchitectureError
├── SubprocessTimeoutError
├── VerificationError
├── TrustError
├── InstallationError
├── HashAlgorithmError
└── XcodeError
```

**Principles:**

- No silent failures — every error is logged
- Pipeline continues on non-critical errors (individual rule failures → findings, not crashes)
- Graceful degradation — if `PreflightEngine` is unavailable, falls back to Doctor checks
- All subprocess calls have explicit timeouts

---

## Development Workflow

```bash
# Clone
git clone https://github.com/rotsl/envguard.git
cd envguard

# Set up dev venv
make install-guardenv

# Run full test suite (264 tests)
make test

# Run linter and type checker
make lint
make typecheck

# Run all quality gates
make check

# Run with coverage
make test-cov

# Format code
make format

# Clean build artifacts
make clean
```

### Running examples

```bash
cd examples/pip-simple
guardenv/bin/envguard init
guardenv/bin/envguard run -- python pip_simple_demo.py

cd examples/mps-intent
guardenv/bin/envguard init
guardenv/bin/envguard preflight
```

### Test structure

```
tests/
├── conftest.py          # Fixtures: macos_host_facts, intel_host_facts, rosetta_host_facts, ...
├── unit/
│   ├── test_detect.py
│   ├── test_exceptions.py
│   ├── test_launch_agent.py
│   ├── test_models.py
│   ├── test_permissions.py
│   ├── test_rules.py
│   ├── test_security.py
│   ├── test_shell_hooks.py
│   ├── test_state.py
│   ├── test_update_manifest.py
│   └── test_wheelcheck.py
└── integration/
    ├── test_cli.py
    ├── test_discovery.py
    └── test_rules_integration.py
```

---

## Contributing

Contributions are welcome. See [docs/contributing.md](docs/contributing.md) for the full guide.

Quick reference:

- **Code style**: enforced by `ruff` (line length 100, pycodestyle + flake8 + isort rules)
- **Type checking**: strict `mypy` (`disallow_untyped_defs`, `strict_optional`)
- **Tests**: pytest, all PRs must pass `make check`
- **Commits**: conventional commits preferred (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
- **PRs**: target the `develop` branch; include test coverage for new functionality

**Issues and feature requests:** [https://github.com/rotsl/envguard/issues](https://github.com/rotsl/envguard/issues)

---

## Limitations

Full details in [docs/limitations.md](docs/limitations.md). Summary:

| Category | Limitation |
| --- | --- |
| **Platform** | macOS is primary. Linux: partial (no LaunchAgent, no MPS). Windows: not supported. |
| **CUDA** | Never supported on macOS — hardware constraint, not a software limitation. |
| **Execution scope** | Only protects `envguard run` entry points. IDE run buttons, direct `python` runs, cron jobs are unprotected. |
| **Shell hooks** | zsh and bash only. No fish, tcsh, ksh. No auto-activation on directory change. |
| **Package managers** | Full support for pip/conda. Detection-only for mamba/uv/pipx/poetry. pdm/hatch/rye/pixi not detected. |
| **Update verification** | Checksum-only (SHA-256). No GPG, no code signing, no certificate pinning. |
| **Concurrency** | No file locking. Concurrent envguard runs on the same project may race. |
| **Monorepos** | Single project root assumption. Multiple `pyproject.toml` files not fully supported. |

---

## License

```
Copyright 2026 Rohan R

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

*envguard is in active development (alpha). APIs and behaviour may change between releases.*
*Repository: [https://github.com/rotsl/envguard](https://github.com/rotsl/envguard)*
