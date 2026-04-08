# Command Reference

Complete reference for all envguard CLI commands.

---

## Global options

All commands support these global flags:

| Flag | Short | Description |
|---|---|---|
| `--json` | `-j` | Output results as JSON instead of Rich-formatted text |

---

## envguard init

Initialize envguard for a project directory. Creates `.envguard/` with state, cache, snapshots, and logs subdirectories.

### Usage

```
envguard init [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory to initialize |
| `--python` | `-p` | auto-detected | Python version to use (e.g., `3.12`) |
| `--env-type` | `-e` | auto-detected | Environment type (`venv` or `conda`) |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Initialize in current directory
envguard init

# Initialize with specific Python version and env type
envguard init --python 3.12 --env-type venv

# Initialize a specific project directory
envguard init /path/to/project

# JSON output
envguard init --json
```

### What it creates

```
<project>/
└── .envguard/
    ├── state.json          # Project metadata and platform info
    ├── .gitignore          # Ignores cache/, snapshots/, logs/, *.tmp
    ├── cache/
    ├── snapshots/
    └── logs/
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Initialized successfully |
| 1 | General error (invalid directory, etc.) |
| 3 | Project directory not found |
| 5 | Permission denied |

---

## envguard doctor

Run comprehensive diagnostics on the host system and project. This is the most thorough check available.

### Usage

```
envguard doctor [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory to diagnose |
| `--json` | `-j` | false | Output results as JSON |

### Diagnostic checks (10 checks)

| Check | What it verifies |
|---|---|
| `host_system` | macOS version, architecture, minimum version (12.0+) |
| `python_installation` | Python version, path, architecture, implementation |
| `package_managers` | Availability of pip, conda, mamba, uv, pipx, poetry |
| `xcode_tools` | Xcode Command Line Tools status (macOS only) |
| `network_connectivity` | PyPI reachable via HTTPS |
| `permissions` | Write access to project dir, home dir, `.envguard` dir, `/tmp` |
| `project_configuration` | Marker files detected, `.envguard` initialized |
| `environment_health` | Active venv/conda detection, Python version match, site-packages |
| `envguard_installation` | Required dependencies (typer, rich) available |
| `accelerator_support` | Apple MPS available, CUDA explicitly unsupported |

### Examples

```bash
envguard doctor
envguard doctor /path/to/project
envguard doctor --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All checks passed |
| 1 | Some checks failed with errors |
| 0 (with warnings) | Checks passed with warnings (no non-zero exit) |

---

## envguard detect

Detect and display host system and project information without running full diagnostics.

### Usage

```
envguard detect [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
envguard detect
envguard detect --json
```

### Output includes

- Host: OS, macOS version, architecture, Python version, Python path
- Project: directory, type (pyproject/setuptools/etc.), envguard status, active environment
- Xcode tools status (macOS only)

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Error |

---

## envguard preflight

Run preflight checks and optionally execute a command if all checks pass.

### Usage

```
envguard preflight [PROJECT_DIR] [COMMAND...] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory |
| `COMMAND...` | | (none) | Command to run after preflight passes |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Run preflight only
envguard preflight

# Run preflight, then execute a command
envguard preflight pytest -v

# JSON output
envguard preflight --json
```

### Preflight behavior

1. Runs all 10 doctor checks.
2. Displays results with status symbols (checkmark, warning, error).
3. If any check has `status: "error"`, exits with code 2.
4. If warnings are present but no errors, continues with a warning message.
5. If a command is provided and preflight passes, executes the command in the active environment.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All checks passed |
| 2 | Preflight checks failed |
| 1 | General error |
| N | Command exit code (if command was provided and failed) |

---

## envguard run

Run a command in a managed environment with preflight checks.

### Usage

```
envguard run -- <COMMAND...> [OPTIONS]
```

The `--` separator is required to distinguish envguard flags from the command to run.

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `COMMAND...` | | (required) | Command and arguments to run |
| `--dir` | `-d` | `.` (cwd) | Project directory |
| `--no-preflight` | | false | Skip preflight checks |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Run pytest with preflight
envguard run -- pytest -v

# Run a Python script
envguard run -- python train.py

# Run without preflight (when you know it's safe)
envguard run --no-preflight -- python script.py

# Specify project directory
envguard run --dir /path/to/project -- python app.py
```

### Managed execution behavior

1. Resolves the project directory.
2. Runs preflight checks (unless `--no-preflight`).
3. Detects the active environment (`.venv`, `venv`, `CONDA_PREFIX`).
4. Prepends the environment's `bin/` directory to `PATH`.
5. Sets `VIRTUAL_ENV` environment variable.
6. Executes the command as a subprocess in the project directory.
7. Returns the subprocess exit code.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Command succeeded |
| 2 | Preflight failed |
| 5 | Permission denied |
| 127 | Command not found |
| N | Command's exit code |

---

## envguard repair

Repair the managed environment for a project. Fixes common issues automatically.

### Usage

```
envguard repair [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory |
| `--json` | `-j` | false | Output results as JSON |

### Repair operations

1. **Create missing state file** — If `state.json` is missing or corrupt, creates a fresh one.
2. **Create missing directories** — Ensures `cache/`, `snapshots/`, `logs/` exist.
3. **Create missing `.gitignore`** — Writes a standard `.gitignore` inside `.envguard/`.
4. **Fix stale environment paths** — If the state references a non-existent environment, removes the reference and re-detects.
5. **Update platform information** — Refreshes the platform info in `state.json`.

### Examples

```bash
envguard repair
envguard repair /path/to/project
envguard repair --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Repairs applied (or no repairs needed) |
| 1 | Repair failed |
| 3 | `.envguard/` not found (run `envguard init` first) |

---

## envguard freeze

Freeze and capture the current environment state as a snapshot.

### Usage

```
envguard freeze [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory |
| `--output` | `-o` | auto | Output file path |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Freeze to default snapshot location
envguard freeze

# Freeze to a specific file (JSON)
envguard freeze --output deps.json

# Freeze to a specific file (text)
envguard freeze --output requirements-frozen.txt
```

### Output format

**JSON** (default when `.envguard/` exists):
```json
{
  "created_at": "2026-07-15T10:30:00",
  "envguard_version": "1.0.1",
  "python_version": "3.12.0",
  "project_dir": "/path/to/project",
  "project_type": "pyproject",
  "active_env": "/path/to/project/.venv",
  "packages": ["numpy==2.0.0", "requests==2.32.0"],
  "package_count": 2,
  "platform": { ... }
}
```

**Text** (when no `.envguard/` or `.txt` output extension):
```
numpy==2.0.0
requests==2.32.0
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Freeze successful |
| 1 | Error (pip freeze failed, permission denied, etc.) |

---

## envguard health

Display focused health status of the managed environment. A subset of `doctor` checks.

### Usage

```
envguard health [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory |
| `--json` | `-j` | false | Output results as JSON |

### Checks performed

| Check | What it verifies |
|---|---|
| `environment_health` | Active venv/conda, Python version match, site-packages |
| `python_installation` | Python version, path, architecture |
| `permissions` | Write access to project dir, home dir, `.envguard` dir |

### Examples

```bash
envguard health
envguard health --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All checks passed |
| 1 | Errors detected (run `envguard repair`) |

---

## envguard update

Check for and apply envguard updates.

### Usage

```
envguard update [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--dry-run` | | false | Check for updates without installing |
| `--channel` | `-c` | `stable` | Update channel (`stable`, `beta`) |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Check for updates (dry run)
envguard update --dry-run

# Install update
envguard update

# Check beta channel
envguard update --channel beta --dry-run

# JSON output
envguard update --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Already up to date, or update installed successfully |
| 1 | Update failed |
| 10 | Update available (informational) |
| 11 | Already up to date (informational) |

---

## envguard rollback

Rollback envguard to a previous snapshot.

### Usage

```
envguard rollback [SNAPSHOT_ID] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `SNAPSHOT_ID` | | (none) | Snapshot ID to rollback to (omit to list) |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# List available snapshots
envguard rollback

# Rollback to a specific snapshot
envguard rollback freeze-2026-07-15T10-30-00

# JSON output
envguard rollback --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Rollback successful, or snapshots listed |
| 1 | Snapshot not found or rollback failed |
| 12 | Rollback failed |

---

## envguard install-shell-hooks

Install optional shell integration hooks for zsh or bash.

### Usage

```
envguard install-shell-hooks [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--shell` | `-s` | auto-detected | Shell type (`zsh` or `bash`) |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
envguard install-shell-hooks
envguard install-shell-hooks --shell zsh
envguard install-shell-hooks --shell bash
```

### What it does

1. Detects your shell (or uses the `--shell` option).
2. Locates the RC file (`~/.zshrc` or `~/.bashrc`).
3. Checks if hooks are already installed (idempotent).
4. Appends the hook block to the RC file.
5. Prints instructions to reload the shell.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Installed (or already installed) |
| 1 | RC file not found or write failed |

---

## envguard uninstall-shell-hooks

Uninstall shell integration hooks.

### Usage

```
envguard uninstall-shell-hooks [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--shell` | `-s` | auto-detected | Shell type (`zsh` or `bash`) |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
envguard uninstall-shell-hooks
envguard uninstall-shell-hooks --shell zsh
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Uninstalled (or not found) |
| 1 | Error |

---

## envguard install-launch-agent

Install the envguard update LaunchAgent for macOS.

### Usage

```
envguard install-launch-agent [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
envguard install-launch-agent
envguard install-launch-agent --json
```

### What it creates

```
~/Library/LaunchAgents/com.envguard.update.plist
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Installed successfully |
| 1 | Error (not macOS, permission denied, etc.) |

---

## envguard uninstall-launch-agent

Uninstall the envguard update LaunchAgent.

### Usage

```
envguard uninstall-launch-agent [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
envguard uninstall-launch-agent
```

### What it does

1. Checks if running on macOS.
2. Unloads the LaunchAgent from launchd (`launchctl unload`).
3. Deletes the plist file.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Uninstalled (or not found) |
| 1 | Error |

---

## envguard status

Display comprehensive status of envguard and the managed environment.

### Usage

```
envguard status [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
envguard status
envguard status /path/to/project
envguard status --json
```

### Output includes

- envguard version
- Project directory and type
- Initialization status
- Active environment path
- Python version and platform
- State timestamps (initialized, last updated)
- Environment type

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Error |

---

## envguard shell-hook

Output shell integration code suitable for use with `eval`.

### Usage

```
envguard shell-hook [OPTIONS]
```

### Options

| Option  | Short | Default       | Description                   |
|---------|-------|---------------|-------------------------------|
| `--shell` | `-s` | auto-detected | Shell type (`zsh` or `bash`) |

### Examples

```bash
# Emit hook code for eval
eval "$(envguard shell-hook)"

# Emit for a specific shell
eval "$(envguard shell-hook --shell zsh)"
```

---

## envguard resolve

Resolve project dependencies to pinned versions using the PyPI JSON API.

### Usage

```
envguard resolve [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory |
| `--python` | `-p` | auto | Target Python version for resolution |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Resolve all project dependencies
envguard resolve

# Resolve for a specific Python version
envguard resolve --python 3.12

# JSON output (list of name==version)
envguard resolve --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Resolved successfully |
| 1 | Resolution failed (dependency conflict, network error) |
| 6 | Network unavailable |

---

## envguard install

Install packages into the managed environment.

### Usage

```
envguard install [PACKAGES...] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PACKAGES...` | | (none) | Package specs to install (e.g., `requests>=2.28`) |
| `--from-lock` | | false | Install all packages pinned in `envguard.lock` |
| `--dev` | | false | Include dev/optional dependency groups |
| `--dir` | `-d` | `.` (cwd) | Project directory |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Install packages listed in pyproject.toml
envguard install

# Install from lock file
envguard install --from-lock

# Install specific packages
envguard install requests==2.31.0 numpy

# Include dev dependencies
envguard install --dev

# JSON output
envguard install --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Installed successfully |
| 1 | Installation failed |
| 3 | Environment not found (run `envguard init`) |

---

## envguard lock

Manage the `envguard.lock` file. Lock commands are sub-commands of `envguard lock`.

### envguard lock generate

Resolve dependencies and write `envguard.lock`.

```bash
envguard lock generate [PROJECT_DIR] [OPTIONS]
```

| Option | Description |
|---|---|
| `--python <version>` | Target Python version for resolution |
| `--json` / `-j` | JSON output |

```bash
envguard lock generate
envguard lock generate --python 3.11
```

### envguard lock update

Re-resolve and refresh `envguard.lock`.

```bash
envguard lock update [PROJECT_DIR] [OPTIONS]
```

| Option | Description |
|---|---|
| `--package <name>` | Update a single package only |
| `--json` / `-j` | JSON output |

```bash
# Update all
envguard lock update

# Update a single package
envguard lock update --package requests
```

### envguard lock sync

Install all packages exactly as pinned in `envguard.lock`.

```bash
envguard lock sync [PROJECT_DIR] [OPTIONS]
```

```bash
envguard lock sync
envguard lock sync --json
```

### envguard lock check

Check whether `envguard.lock` is up-to-date. Exits with code 13 if stale.

```bash
envguard lock check [PROJECT_DIR] [OPTIONS]
```

```bash
# Returns 0 if fresh, 13 if stale
envguard lock check

# Use in CI
envguard lock check || echo "Lock file is stale — run: envguard lock generate"
```

### Lock sub-command exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Error (network failure, parse error) |
| 13 | Lock file stale (`lock check` only) |

---

## envguard publish

Build the project as a distribution (sdist + wheel) and upload to PyPI.

### Usage

```
envguard publish [PROJECT_DIR] [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `PROJECT_DIR` | | `.` (cwd) | Project directory to publish |
| `--token` | | `$PYPI_TOKEN` env var | PyPI API token |
| `--repository` | | PyPI | Upload repository URL |
| `--dry-run` | | false | Build only, do not upload |
| `--skip-build` | | false | Upload existing `dist/` artifacts |
| `--json` | `-j` | false | Output results as JSON |

### Examples

```bash
# Build and upload to PyPI
envguard publish

# Dry run (build only)
envguard publish --dry-run

# Upload to Test PyPI
envguard publish --repository https://test.pypi.org/legacy/

# Upload pre-built artifacts
envguard publish --skip-build
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Published successfully |
| 1 | Build or upload failed |
| 14 | Publish failed |
