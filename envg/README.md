# envguard-tool

**macOS-first Python environment orchestration framework**

[![PyPI version](https://img.shields.io/pypi/v/envguard-tool)](https://pypi.org/project/envguard-tool/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-informational.svg)](#platform-support)

> **Note:** The PyPI distribution name is `envguard-tool`. The installed CLI command and Python import name are both `envguard`.

---

## What is envguard?

envguard is a CLI tool that **detects, validates, orchestrates, and guards Python environments**. It catches problems *before* you run your code — not after a cryptic traceback.

Instead of `python train.py` (and hoping for the best), you run `envguard run -- python train.py`. Before execution envguard runs a **preflight pipeline** that verifies:

- Platform compatibility and macOS version
- Python architecture — Apple Silicon (arm64) vs Intel (x86_64) vs Rosetta 2
- Package manager health (pip, conda, mamba, uv, poetry)
- Dependency conflicts and wheel architecture compatibility
- GPU accelerator availability (MPS on Apple Silicon; CUDA flagged as unsupported on macOS)
- Environment integrity, permissions, and ownership

If anything is wrong, execution is **blocked** with a clear, actionable error. If everything passes, your command runs in the validated environment.

Beyond validation, envguard also handles:

- **Dependency resolution** — resolve project deps to a pinned set via the PyPI JSON API
- **Package installation** — install into venv/uv/conda/mamba environments
- **Lock file management** — generate and sync `envguard.lock`

---

## Installation

```bash
pip install envguard-tool

# Verify
envguard --version
```

**Requirements:**

| Requirement | Version |
|---|---|
| Python | 3.10, 3.11, or 3.12 |
| macOS | 12.0 (Monterey)+ for full feature set |
| Linux | Ubuntu, Debian, Fedora, Arch — partial support |
| Windows | Not supported |

---

## Quick Start

```bash
cd /path/to/your/project

# Check your host and project setup
envguard doctor

# Initialise envguard for this project
envguard init

# Run a command with full preflight validation
envguard run -- pytest -v
envguard run -- python train.py
envguard run -- jupyter lab

# Resolve dependencies to pinned versions
envguard resolve

# Generate a lock file
envguard lock generate

# Install from the lock file
envguard install --from-lock
```

---

## All Commands

### Environment management

| Command | Description |
|---|---|
| `envguard init` | Initialise envguard state for the current project |
| `envguard doctor` | Full host and project diagnostic report |
| `envguard detect` | Show detected host facts (OS, arch, Python, tools) |
| `envguard preflight` | Run the preflight validation pipeline |
| `envguard run -- <cmd>` | Run a command after passing preflight |
| `envguard repair` | Auto-repair broken or inconsistent environments |
| `envguard freeze` | Capture a snapshot of the current environment |
| `envguard rollback [snapshot-id]` | Restore environment to a previous snapshot |
| `envguard health` | Show environment health report |
| `envguard status` | Show current project and environment status |

### Dependency management

| Command | Description |
|---|---|
| `envguard resolve` | Resolve project deps to pinned versions via PyPI API |
| `envguard install [packages]` | Install packages (or project deps, or from lock) |
| `envguard install --from-lock` | Sync environment exactly to `envguard.lock` |
| `envguard install --dev` | Include dev/optional dependency groups |

### Lock file

| Command | Description |
|---|---|
| `envguard lock generate` | Resolve and write `envguard.lock` |
| `envguard lock update` | Re-resolve and refresh `envguard.lock` |
| `envguard lock update --package <name>` | Update a single package in the lock |
| `envguard lock sync` | Sync environment to match lock file exactly |
| `envguard lock check` | Check if lock file is up-to-date (exit 13 if stale) |

### Updates and self-management

| Command | Description |
|---|---|
| `envguard update` | Check for and apply envguard updates |
| `envguard update --dry-run` | Check for updates without applying |

### Shell and launchd integration

| Command | Description |
|---|---|
| `envguard install-shell-hooks` | Install zsh/bash shell integration |
| `envguard uninstall-shell-hooks` | Remove shell integration |
| `envguard shell-hook` | Emit shell hook code (for use with `eval`) |
| `envguard install-launch-agent` | Install macOS launchd periodic update checker |
| `envguard uninstall-launch-agent` | Remove the launchd agent |

---

## The Preflight Pipeline

`envguard run` and `envguard preflight` execute a 9-step pipeline:

| Step | Name | What it does | Fails if |
|---|---|---|---|
| 1 | Host detect | OS, arch, Python, tools, network | Unsupported platform |
| 2 | Project discover | pyproject.toml, requirements.txt, environment.yml, setup.py | Project root not found |
| 3 | Intent analyze | Infer env type, Python version, accelerator targets | — |
| 4 | Rules evaluate | Run 15+ validation rules | Any CRITICAL rule fires |
| 5 | Fail-fast | Block on unrecoverable issues | CUDA on macOS, arch mismatch |
| 6 | Resolution | Choose package manager + Python version | No compatible Python found |
| 7 | Env create/repair | Create venv or repair existing env | Creation fails |
| 8 | Validate | Dependency consistency check | pip check fails |
| 9 | Smoke test | Import key packages | Import error |

---

## Lock File Format

`envguard.lock` is a TOML file written to the project root:

```toml
# envguard.lock — generated by envguard
# Do not edit manually. Regenerate with: envguard lock generate

[metadata]
envguard_version = "1.0.0"
generated_at = "2026-04-08T12:00:00+00:00"
python_requires = ">=3.10"
content_hash = "sha256:abc123..."
sources = ["pyproject.toml"]

[[package]]
name = "requests"
version = "2.31.0"
specifier = "requests==2.31.0"
source = "pypi"
```

Commit `envguard.lock` to version control. Use `envguard lock check` in CI to detect stale locks (exits with code 13 if stale).

---

## Configuration

Create `envguard.toml` in your project root:

```toml
[envguard]
env_type = "venv"           # venv | conda | mamba | auto
python_version = "3.11"     # pinned Python version
auto_repair = true          # auto-repair on preflight failure
fail_fast = true            # stop on first CRITICAL finding

[envguard.update]
policy = "stable"           # stable | beta | off
check_on_run = true         # check for updates before envguard run
```

---

## Environment Variables

| Variable | Effect |
|---|---|
| `ENVGUARD_DISABLED` | Set to `1` to skip all preflight checks |
| `ENVGUARD_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## JSON Output

Every command supports `--json` / `-j` for machine-readable output:

```bash
envguard doctor --json | jq '.checks[] | select(.status == "error")'
envguard resolve --json | jq '.packages[] | .name + "==" + .version'
envguard lock check --json
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error |
| 2 | Preflight failed |
| 3 | Environment not found |
| 4 | Environment corrupt |
| 5 | Permission denied |
| 6 | Network unavailable |
| 7 | Platform not supported |
| 8 | Configuration error |
| 10 | Update available |
| 11 | Already up to date |
| 12 | Rollback failed |
| 13 | Lock file stale |
| 14 | Publish failed |

---

## Platform Support

| Platform | Level | Notes |
|---|---|---|
| **macOS 12+ (Monterey+)** | **Full** | All features. Primary target. |
| **macOS 11 (Big Sur)** | Partial | Below recommended minimum. |
| **Linux (Ubuntu, Debian, Fedora, Arch)** | Partial | Core pipeline works. No LaunchAgent, no MPS. |
| **Windows** | Not supported | — |

macOS-only features: `install-launch-agent`, MPS/Metal detection, Rosetta 2 detection, Xcode CLI tools check.

---

## Source Code

Source code and issue tracker:
**https://github.com/rotsl/envguard**

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
