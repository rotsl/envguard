# Limitations

This document provides a comprehensive list of envguard's limitations, known edge cases, and design trade-offs.

---

## Platform limitations

### macOS only (initial version)

envguard is designed and tested for macOS. While the codebase has some Linux compatibility (Linux is listed in classifiers), the primary target is macOS with Apple Silicon and Intel architectures.

**Impact:** Some features (LaunchAgent, MPS detection, Xcode CLI tools, Rosetta detection) are macOS-specific and will produce "not applicable" results on Linux.

**Future plans:** Linux support may be improved in future versions, but macOS will remain the primary platform.

### No Windows support

envguard does not support Windows. There are no plans for Windows support in the current roadmap. The codebase uses POSIX-specific APIs (`os.access`, `os.path`, subprocess patterns) that do not translate to Windows.

---

## GPU and accelerator limitations

### CUDA is NOT supported on macOS

Apple Silicon hardware cannot run NVIDIA CUDA. This is a hardware constraint, not a software limitation. envguard will detect any CUDA dependency on macOS and produce a critical finding.

**Affected scenarios:**
- Projects that depend on `torch` with CUDA-specific wheels (e.g., `torch==2.0.0+cu118`)
- Projects that explicitly depend on `nvidia-*` packages
- Projects that set `accelerator_target = "cuda"` in configuration

**Alternatives on macOS:**
- Apple MPS (Metal Performance Shaders) — available on macOS 12.3+ with Apple Silicon
- CPU — always available, always works

### MPS has limited framework support

Not all ML frameworks support MPS. As of this writing:

| Framework | MPS Support | Notes |
|---|---|---|
| PyTorch | Yes | `torch.backends.mps.is_available()` |
| mlx | Yes | Apple's own ML framework |
| TensorFlow | Partial | `tensorflow-metal` plugin required, not all ops supported |
| JAX | Partial | Experimental MPS backend |
| NumPy/SciPy | No | CPU-only (no GPU acceleration) |

envguard detects MPS availability based on macOS version (12.3+) and architecture (arm64), but cannot verify framework-level MPS support without importing the framework.

---

## Execution model limitations

### Cannot control unmanaged process launches

envguard only validates entry points that are explicitly routed through `envguard run -- <command>` or `envguard preflight`. Processes launched by other means are not validated:

- Double-clicking a Python script in Finder
- IDE run buttons (VS Code, PyCharm)
- Cron jobs
- LaunchDaemons
- Other terminal sessions that don't use envguard

**Recommendation:** Always use `envguard run` for production and CI/CD workflows. For IDE integration, configure the IDE to use `envguard run` as the Python interpreter command.

### LaunchAgent only checks updates, doesn't intercept processes

The macOS LaunchAgent installed by `envguard install-launch-agent` performs a single function: periodic update checks via `envguard update --dry-run`. It does NOT:

- Intercept or modify subprocess launches
- Watch for directory changes
- Automatically activate environments
- Run preflight checks on new terminal sessions

For automatic environment activation on directory changes, use the shell hooks (`envguard install-shell-hooks`) or a tool like `direnv`.

---

## Dependency and environment limitations

### Limited to detected package managers

envguard detects and works with the following package managers:

| Manager | Detection | Support Level |
|---|---|---|
| pip | Full | venv creation, dependency installation, freeze |
| conda | Full | Environment creation, dependency installation |
| uv | Full | Preferred backend for resolution and installation when available |
| mamba | Partial | Detected as available, treated like conda for operations |
| pipx | Detection only | Detected as available |
| poetry | Detection only | Environment type inferred from `poetry.lock` |

Package managers not listed above (e.g., `pdm`, `hatch`, `rye`, `pixi`) are not detected and their environments may not be correctly identified.

### Cannot support every codebase with zero exceptions

envguard's project discovery and rules engine handle common project layouts, but there are edge cases:

1. **Custom build systems** — Projects using custom build backends not recognized by envguard may not have their dependencies correctly parsed.
2. **Monorepos** — Multi-project repositories with multiple `pyproject.toml` files may confuse envguard's single-root assumption.
3. **Conditional dependencies** — `pyproject.toml` markers (`; sys_platform == "darwin"`) are parsed but not fully resolved during preflight.
4. **Workspace dependencies** — Projects using PEP 735 workspace dependencies are not supported.
5. **Editable installs** — `pip install -e .` is supported during repair, but the editable link may break if the project directory moves.

### Shell integration is opt-in and limited

Shell hooks are not installed by default and only support zsh and bash. They do NOT:

- Automatically activate environments on directory change
- Provide command completion beyond what the installed block includes
- Support fish, tcsh, ksh, or other shells
- Modify the prompt or display environment status

---

## Update mechanism limitations

### Update verification is checksum-only (no code signing)

envguard verifies update integrity via SHA-256 checksum comparison. There is no:

- GPG signature verification
- Apple code signing validation
- Certificate pinning for HTTPS connections
- Reproducible build verification

This means a compromised release server that serves a correctly-checksummed malicious package would bypass envguard's verification.

### No mirror or fallback URLs

The update manifest is fetched from a single URL (`https://releases.envguard.dev/manifest.json`). If this server is unreachable, update checks fail. There is no CDN, mirror, or fallback mechanism.

### Rollback is snapshot-based, not version-based

Rollback restores a snapshot of the envguard package files, not a specific version. If the snapshot was taken after a partial update, rollback may not fully restore the previous version.

---

## Network limitations

### Cannot force internet access

If the network is unavailable, envguard will detect it and produce warnings, but it cannot make the internet work. Operations that require network access (update checks, PyPI connectivity, package downloads) will fail gracefully.

### No offline package cache management

envguard does not manage a local package cache. If you need offline installation, use pip's `--cache-dir` option or maintain a local PyPI mirror separately.

### Proxy support is environment-variable only

envguard relies on `HTTPS_PROXY` and `HTTP_PROXY` environment variables for proxy configuration. There is no built-in proxy configuration or PAC file support.

---

## Security limitations

### No sandboxing

envguard runs with the user's full permissions. It does not sandbox subprocess execution, restrict file system access, or limit network connections.

### No audit logging to external systems

Logs are written to local files only. There is no syslog integration, SIEM forwarding, or centralized log aggregation.

### No integrity monitoring

envguard does not monitor its own binary or installed files for tampering between runs. If an attacker modifies envguard's files between invocations, the modification will not be detected.

### State files are not encrypted

All state files (`.envguard/state.json`, `.envguard/resolution.json`, snapshots) are stored as plain JSON. Sensitive information (if any) in these files is not encrypted.

---

## Known edge cases

### Projects without any marker files

If a project has no `pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile`, `environment.yml`, `poetry.lock`, or `.python-version`, envguard's project discovery will produce an empty `ProjectIntent` with `environment_type: UNKNOWN`. Preflight will still work but with reduced information.

### Corrupted state.json

If `.envguard/state.json` contains invalid JSON, envguard will return `None` from `load_json_file()` and use default values. The `repair` command will recreate the state file.

### Environment directory is a symlink

envguard follows symlinks when checking environment paths via `Path.resolve()`. If `.venv` is a symlink, the actual environment directory is used for all operations.

### Multiple Python versions installed

envguard uses `sys.executable` and `shutil.which()` to find Python. If multiple versions are installed, the first one on `PATH` is used. Use `pyenv` or explicit paths to control which Python is selected.

### Very large dependency lists

envguard loads all dependencies from `requirements.txt` and `pyproject.toml` into memory. Projects with thousands of dependencies may use significant memory during preflight. There is no hard limit, but performance may degrade.

### Concurrent envguard runs

envguard does not use file locking for state files. Concurrent runs (e.g., from multiple terminals or CI workers targeting the same project) may produce race conditions. The `.envguard/envguard.lock` file is defined but not yet implemented.

### Timeouts on slow networks

Subprocess timeouts are set to conservative values (5-300 seconds). On very slow networks, operations like `pip install` may time out. Increase timeouts by modifying the source or setting `PIP_TIMEOUT` if supported.

---

## Design trade-offs

| Trade-off | Choice | Rationale |
|---|---|---|
| Explicit vs. implicit activation | Explicit (`envguard run`) | Safer; user always knows when preflight is running |
| Strict vs. lenient rules | Strict (fail on CUDA on macOS) | Prevents cryptic runtime errors |
| Global vs. project config | Project-first with global fallback | Projects have different needs |
| Auto-repair vs. manual | Manual-first with auto-repair option | Avoids surprising mutations |
| Checksum-only vs. code signing | Checksum-only | Simpler; code signing infrastructure is complex |
| Single vs. multi-project | Single project root | Simpler model; monorepos are an edge case |
