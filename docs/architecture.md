# Architecture

This document describes the high-level architecture of envguard, including module organization, the core pipeline, data flow, state management, and error handling strategy.

---

## Overview

envguard is structured as a layered Python application with clear separation between the CLI layer, orchestration engines, domain logic, and platform-specific modules. It follows a pipeline pattern: each command triggers a sequence of well-defined stages that transform raw system state into actionable findings.

The architecture prioritizes:

- **Explicit over implicit** — every check is a named rule with a known ID.
- **Composable** — rules, detectors, and resolvers can be run independently or as a pipeline.
- **Observable** — all operations produce structured data models, not just side effects.
- **Graceful degradation** — individual failures do not crash the pipeline; they produce findings.

---

## Module dependency diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLI Layer                                  │
│                    cli.py (Typer app)                               │
│                  __main__.py (python -m)                            │
└──────────────┬──────────────────────────────┬──────────────────────┘
               │                              │
       ┌───────▼───────┐              ┌───────▼───────┐
       │   doctor.py   │              │   preflight   │
       │  (diagnostics)│              │  (pipeline)   │
       └───────┬───────┘              └───────┬───────┘
               │                              │
       ┌───────▼──────────────────────────────▼───────┐
       │              Orchestration Layer              │
       │                                               │
       │   ┌───────────┐  ┌──────────┐  ┌──────────┐ │
       │   │  detect   │  │  rules   │  │  repair  │ │
       │   │  (host)   │  │ (engine) │  │ (engine) │ │
       │   └─────┬─────┘  └────┬─────┘  └────┬─────┘ │
       └─────────┼─────────────┼────────────┼────────┘
                 │             │            │
       ┌─────────▼─────────────▼────────────▼────────┐
       │               Domain Layer                   │
       │                                               │
       │  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
       │  │  models  │  │exceptions│  │  logging   │ │
       │  └──────────┘  └──────────┘  └────────────┘ │
       │                                               │
       │  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
       │  │ project/ │  │ resolver/│  │  update/   │ │
       │  │ discovery│  │pypi_res. │  │ updater    │ │
       │  │ intent   │  │uv_backend│  │ manifest   │ │
       │  │resolution│  │pip/conda │  │ verifier   │ │
       │  │ lifecycle│  │inference │  │ rollback   │ │
       │  └──────────┘  │markers   │  └────────────┘ │
       │                │wheelcheck│                  │
       │  ┌──────────┐  └──────────┘  ┌────────────┐ │
       │  │  lock/   │                │  publish/  │ │
       │  │ manager  │  ┌──────────┐  │ builder    │ │
       │  └──────────┘  │installer │  │ uploader   │ │
       │                └──────────┘  └────────────┘ │
       └─────────────────┬───────────────────────────┘
                         │
       ┌─────────────────▼───────────────────────────┐
       │            Platform Layer                     │
       │                                               │
       │  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
       │  │  macos/  │  │ security/│  │  launch/   │ │
       │  │permissions│  │signatures│  │  runner    │ │
       │  │ paths    │  │ trust    │  │shell_hooks │ │
       │  │ rosetta  │  │          │  │launch_agent│ │
       │  │ xcode    │  │          │  │            │ │
       │  │system_in.│  │          │  │            │ │
       │  └──────────┘  └──────────┘  └────────────┘ │
       └─────────────────────────────────────────────┘
```

### Module responsibilities

| Module | Responsibility |
|---|---|
| `cli.py` | Typer CLI application with 25 commands across 6 groups, error handling, Rich formatting |
| `doctor.py` | 10 diagnostic checks for host and project health |
| `preflight.py` | Full preflight pipeline orchestration (9 steps) |
| `detect.py` | Host system detection (OS, arch, Python, shell, network, permissions) |
| `rules.py` | Rules engine evaluating 15+ preflight rules |
| `repair.py` | Automated repair: environment recreation, ownership fixes, Python switching |
| `installer.py` | Package installation/uninstallation with backend auto-detection (uv > pip > conda) |
| `state.py` | Atomic JSON state persistence for `.envguard/state.json` |
| `models.py` | All data models: `HostFacts`, `ProjectIntent`, `ResolutionRecord`, `RuleFinding`, `ResolvedPackage`, `LockFile`, `InstallResult`, `PublishResult`, enums |
| `exceptions.py` | Custom exception hierarchy (`EnvguardError` + 18 subclasses including `LockFileError`, `PublishError`) |
| `logging.py` | Structured logging via `get_logger()` |
| `project/discovery.py` | Scans project files to build `ProjectIntent` |
| `project/intent.py` | Analyzes intent: accelerator targets, compatibility, recommendations |
| `project/resolution.py` | Resolves Python version, package manager, env type, path, accelerator |
| `project/lifecycle.py` | Full lifecycle: init, preflight, run, repair, health, freeze |
| `resolver/pypi_resolver.py` | BFS dependency resolution via PyPI JSON API |
| `resolver/uv_backend.py` | uv backend: wraps `uv pip compile` / `uv pip install` |
| `resolver/pip_backend.py` | pip-based dependency resolution |
| `resolver/conda_backend.py` | conda/mamba environment and dependency resolution |
| `resolver/inference.py` | `infer_requirements()` and `infer_sources()` from project files |
| `resolver/markers.py` | PEP 508 environment marker evaluation |
| `resolver/wheelcheck.py` | Wheel platform and architecture compatibility checks |
| `lock/manager.py` | `LockManager`: generate, read, write, sync `envguard.lock` (TOML) |
| `publish/builder.py` | `Builder`: invoke `python -m build` to produce sdist + wheel |
| `publish/uploader.py` | `Uploader`: upload artifacts via twine or direct urllib multipart POST |
| `macos/permissions.py` | Permission checking: filesystem, network, subprocess, LaunchAgent |
| `macos/paths.py` | macOS-specific path definitions |
| `macos/rosetta.py` | Rosetta 2 translation detection |
| `security/signatures.py` | SHA-256/384/512 hash computation and verification |
| `security/trust.py` | Trust boundary evaluation |
| `update/updater.py` | Self-update: manifest fetch, download, stage, apply |
| `update/manifest.py` | Manifest parsing, validation, version comparison |
| `update/verifier.py` | Update integrity verification |
| `update/rollback.py` | Snapshot creation and rollback |
| `launch/runner.py` | Managed subprocess execution |
| `launch/shell_hooks.py` | zsh/bash rc file management |
| `launch/launch_agent.py` | macOS LaunchAgent plist management |

---

## Core pipeline

The central concept in envguard is the **preflight pipeline**, which flows through six major stages:

```
Discovery → Detection → Rules → Resolution → Preflight → Launch
```

### Stage 1: Discovery

`ProjectDiscovery` scans the project directory for marker files in a defined priority order:

1. `pyproject.toml`
2. `requirements.txt` (and `requirements-dev.txt`, `requirements-prod.txt`)
3. `environment.yml` / `environment.yaml`
4. `setup.py`
5. `Pipfile`
6. `poetry.lock`
7. `pixi.toml`
8. `.python-version`
9. Previous `.envguard/` state

It parses TOML files with `tomllib`, reads requirements files line-by-line, and uses AST parsing for `setup.py` (no `exec()`). The output is a `ProjectIntent` dataclass.

### Stage 2: Detection

`HostDetector` probes the live system to build a `HostFacts` snapshot:

- **OS**: `platform.system()`, `platform.mac_ver()`
- **Architecture**: `platform.machine()` + `sysctl proc_translated` for Rosetta detection + `file` subprocess for binary architecture verification
- **Python**: `shutil.which()` for python3/pip/conda/mamba, subprocess version checks, `venv` module availability
- **Shell**: `$SHELL` env var parsing
- **Xcode CLI**: `xcode-select -p`
- **Network**: TCP socket to `pypi.org:443` with 5-second timeout
- **Permissions**: `os.access()` for write/execute/read on project dir, home dir, `.envguard` dir, `/tmp`
- **MPS**: OS version check (macOS 12.3+ required)

### Stage 3: Rules

`RulesEngine.evaluate()` runs 15+ rules in sequence. Each rule is a method that returns `None` (pass) or a `RuleFinding` (issue). Rules never short-circuit — all rules run so the caller gets a complete picture.

Rules include: `check_platform_compatibility`, `check_architecture_compatibility`, `check_python_version`, `check_cuda_on_macos`, `check_mps_availability`, `check_rosetta_risk`, `check_wheel_compatibility`, `check_mixed_pip_conda`, `check_source_build_prerequisites`, `check_network_for_operations`, `check_environment_exists`, `check_dependency_conflicts`, `check_stale_environment`, `check_missing_package_manager`, `check_package_manager_health`.

### Stage 4: Resolution

`ResolutionManager` takes the findings and produces a `ResolutionRecord` that addresses them. It determines:

- **Python version**: recommended → required → system → fallback (3.11)
- **Package manager**: intent match → env type fallback → pip
- **Environment type**: recommendation → detection → venv
- **Environment path**: conda vs venv path logic
- **Accelerator**: MPS on macOS, CUDA elsewhere, CPU default

### Stage 5: Preflight

`PreflightEngine.run()` orchestrates the full 9-step pipeline:

1. Detect host facts
2. Discover project
3. Analyze intent
4. Evaluate rules
5. Fail-fast if any CRITICAL findings
6. Create or validate resolution
7. Create or repair environment if needed
8. Validate environment (Python binary, pip functional)
9. Smoke-test key imports (subprocess-isolated)
10. Return `PreflightResult`

### Stage 6: Launch

`envguard run` executes the user's command in the managed environment. It:

1. Activates the environment by prepending `ENV/bin` to `PATH`
2. Sets `VIRTUAL_ENV` or `CONDA_PREFIX` as needed
3. Runs the command as a subprocess in the project directory
4. Returns the subprocess exit code

---

## Data flow

```
Project files ──► ProjectDiscovery ──► ProjectIntent
                                              │
System calls ──► HostDetector ──► HostFacts ──► RulesEngine ──► findings[]
                                                        │
                                                        ▼
                                              ResolutionManager ──► ResolutionRecord
                                                                     │
                                                                     ▼
                                              PreflightEngine ──► PreflightResult
                                                                     │
                                                    ┌────────────────┤
                                                    ▼                ▼
                                              CLI output     Subprocess launch
```

All intermediate results are first-class data structures (dataclasses), not just printed output. This enables:
- JSON output via `--json` flag
- Programmatic consumption by other tools
- Audit trails and logging
- Testability without subprocess mocking

---

## State management

envguard maintains state at two levels:

### Project-level state (`.envguard/`)

| File | Purpose |
|---|---|
| `state.json` | Project metadata: type, Python version, env type, platform info, timestamps |
| `resolution.json` | Latest resolution record |
| `envguard.toml` | Project-specific configuration overrides |
| `envguard.lock` | Lock file for concurrent access (future use) |
| `snapshots/` | Environment freeze snapshots (timestamped JSON) |
| `cache/` | Downloaded manifests, wheel caches |
| `logs/` | envguard log files |
| `backups/` | Environment backups created before repair operations |

### User-level state (`~/.envguard/`)

| Directory/File | Purpose |
|---|---|
| `~/.envguard/snapshots/` | Global rollback snapshots for envguard updates |
| `~/.envguard/cache/updates/` | Staged update archives |
| `~/.envguard/cache/updates/staging/` | Temporary extraction directory for updates |

State files are written atomically (write to `.tmp`, then `os.rename()`) to prevent corruption from interrupted writes.

---

## Ownership model (pip vs conda)

envguard tracks package ownership to detect mixed pip/conda installations, which are a common source of environment corruption.

**Detection strategy:**

1. Check if the environment has a `conda-meta/` directory → it's a conda environment.
2. List packages in `conda-meta/*.json` → these are conda-owned.
3. List packages in `site-packages/*.dist-info/` → these are pip-installed.
4. Compute the intersection → these are mixed-ownership packages.

**Rules:**
- Mixed ownership produces a `WARNING` finding.
- More than 10 pip-only packages in a conda environment produces an `INFO` finding.
- The repair engine can fix this via `conda-unpack` or selective reinstallation.

---

## Error handling strategy

### Exception hierarchy

All envguard errors inherit from `EnvguardError`. Specialized exceptions carry structured metadata:

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
├── XcodeError
├── LockFileError
└── PublishError
```

### Error handling principles

1. **No silent failures** — every error is logged at the appropriate level.
2. **Pipeline continues on non-critical errors** — individual rule failures produce findings, not crashes.
3. **Graceful degradation** — if a sub-module (e.g., `ProjectDiscovery`) is unavailable, the preflight engine falls back to built-in implementations.
4. **Subprocess timeouts** — all subprocess calls have explicit timeouts (5–300 seconds depending on the operation).
5. **Atomic writes** — state files are written via a tmp+rename pattern.

---

## Exit code design

envguard uses specific exit codes to communicate the type of failure:

| Code | Constant | Meaning |
|---|---|---|
| 0 | `EXIT_OK` | Success |
| 1 | `EXIT_GENERAL_ERROR` | Unspecified error |
| 2 | `EXIT_PREFLIGHT_FAILED` | Preflight checks failed |
| 3 | `EXIT_ENV_NOT_FOUND` | Environment not found |
| 4 | `EXIT_ENV_CORRUPT` | Environment is corrupted |
| 5 | `EXIT_PERMISSION_DENIED` | Permission error |
| 6 | `EXIT_NETWORK_ERROR` | Network unavailable |
| 7 | `EXIT_UNSUPPORTED_PLATFORM` | Platform not supported |
| 8 | `EXIT_CONFIG_ERROR` | Configuration error |
| 10 | `EXIT_UPDATE_AVAILABLE` | Update is available |
| 11 | `EXIT_ALREADY_UP_TO_DATE` | Already at latest version |
| 12 | `EXIT_ROLLBACK_FAILED` | Rollback operation failed |
| 13 | `EXIT_LOCK_STALE` | Lock file is missing or out of date |
| 14 | `EXIT_PUBLISH_FAILED` | Package publish failed |

Exit code 9 is intentionally skipped to avoid confusion with the Unix `SIGKILL` convention.
