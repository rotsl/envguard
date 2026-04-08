# Threat Model

This document describes the threat model for envguard, identifying trust boundaries, attack surfaces, mitigations, and security assumptions.

---

## Trust boundaries

envguard operates across several trust boundaries:

```
┌─────────────────────────────────────────────────────────┐
│                    UNTRUSTED                             │
│                                                         │
│  Remote update server  •  PyPI  •  Project dependencies │
│  Downloaded archives   •  Manifest JSON                 │
└──────────────┬──────────────────────┬───────────────────┘
               │                      │
        ┌──────▼──────┐       ┌───────▼───────┐
        │  Network I/O │       │  Filesystem    │
        │  (HTTPS)     │       │  (project dir) │
        └──────┬──────┘       └───────┬───────┘
               │                      │
┌──────────────▼──────────────────────▼───────────────────┐
│                    SEMI-TRUSTED                          │
│                                                         │
│  Shell RC files  •  LaunchAgent plists                  │
│  Project config  •  Downloaded wheel archives           │
└──────────────┬──────────────────────┬───────────────────┘
               │                      │
        ┌──────▼──────┐       ┌───────▼───────┐
        │  Subprocess  │       │  State files   │
        │  execution   │       │  (.envguard/)  │
        └──────┬──────┘       └───────┬───────┘
               │                      │
┌──────────────▼──────────────────────▼───────────────────┐
│                    TRUSTED                               │
│                                                         │
│  envguard codebase  •  Python runtime  •  macOS APIs    │
│  Host system tools  •  Package managers (pip/conda)     │
└─────────────────────────────────────────────────────────┘
```

### Boundary descriptions

1. **Untrusted** — Remote content from the update server, PyPI, and project dependencies. Any of these could be malicious or compromised.

2. **Semi-trusted** — Files that envguard reads or writes but that could be tampered with by other processes or users on the same machine. Shell RC files and LaunchAgent plists are shared with the rest of the system.

3. **Trusted** — envguard's own code, the Python runtime, macOS system APIs, and system-installed package managers. These are assumed to be correctly installed and not actively malicious.

---

## Attack surfaces

### 1. Update mechanism

**Risk**: An attacker who compromises the update manifest server could serve a malicious update package.

**Components involved**: `update/updater.py`, `update/manifest.py`, `update/verifier.py`

**Attack vector**: Man-in-the-middle on HTTPS connection to `releases.envguard.dev`, or compromise of the release server itself.

### 2. Subprocess execution

**Risk**: If user-controlled input reaches subprocess calls without sanitization, command injection could occur.

**Components involved**: `detect.py`, `rules.py`, `repair.py`, `preflight.py`, `launch/runner.py`, `cli.py`

**Attack vector**: Crafted project file names, dependency names, or environment variable values that are interpolated into shell commands.

### 3. Shell integration

**Risk**: The shell hook writes to `~/.zshrc` or `~/.bashrc`, which are executed on every shell startup.

**Components involved**: `launch/shell_hooks.py`, `cli.py` (install/uninstall commands)

**Attack vector**: A compromised envguard writing malicious code to shell RC files.

### 4. File permissions

**Risk**: envguard creates and modifies files in project directories, `~/.envguard/`, and `~/Library/LaunchAgents/`. An attacker with write access to these locations could tamper with envguard's state.

**Components involved**: `macos/permissions.py`, `cli.py` (init, repair, freeze, update commands)

**Attack vector**: Symlink attacks on state files, permission escalation via LaunchAgent plist tampering.

### 5. State file tampering

**Risk**: `state.json` and `resolution.json` influence preflight behavior. Tampered state could cause envguard to skip checks or use incorrect environment paths.

**Components involved**: `__init__.py` (save/load), `project/resolution.py`, `project/lifecycle.py`

**Attack vector**: Direct modification of `.envguard/` files by another user or process.

### 6. Project file parsing

**Risk**: envguard parses `pyproject.toml`, `requirements.txt`, `setup.py`, and `environment.yml`. Malformed or malicious files could trigger unexpected behavior.

**Components involved**: `project/discovery.py`, `project/intent.py`

**Attack vector**: Extremely large files (DoS), malformed TOML/JSON, `setup.py` with dangerous side effects (mitigated by AST-only parsing).

---

## Mitigations

### Update mechanism

| Mitigation | Implementation |
|---|---|
| **SHA-256 checksum verification** | Every downloaded update archive is verified against the manifest's checksum before staging. `security/signatures.py` implements chunked file hashing. |
| **No `eval()` on remote content** | Manifests are parsed as JSON only. No code execution. |
| **HTTPS-only downloads** | All network requests use `https://` URLs. HTTP is rejected by manifest validation. |
| **Platform validation** | Updates include a `platforms` field; updates targeting wrong platforms are rejected. |
| **Atomic staging** | Updates are extracted to a staging directory and only applied after verification passes. |
| **Rollback support** | A snapshot is created before applying updates. If the update breaks envguard, rollback restores the previous version. |

### Subprocess execution

| Mitigation | Implementation |
|---|---|
| **No shell injection** | All subprocess calls use list-form arguments (`subprocess.run(["cmd", "arg"])`), never string-form with `shell=True`. |
| **Explicit timeouts** | Every subprocess call has a timeout (5–300 seconds). |
| **No `eval()` or `exec()`** | `setup.py` is parsed with `ast.parse()`, never executed. |
| **Path validation** | File paths are resolved via `Path.resolve()` to prevent symlink traversal. |
| **Command not found handling** | `FileNotFoundError` from subprocess is caught and reported as exit code 127. |

### Shell integration

| Mitigation | Implementation |
|---|---|
| **Opt-in only** | Shell hooks are never installed automatically. User must run `envguard install-shell-hooks`. |
| **Minimal hook block** | The installed block is a fixed 5-line snippet. No dynamic content is inserted. |
| **Idempotent** | Running install twice is a no-op; the existing block is detected by a comment marker. |
| **Clean uninstall** | `uninstall-shell-hooks` removes exactly the block that was installed, nothing more. |

### File permissions

| Mitigation | Implementation |
|---|---|
| **Permission checks before writes** | `PermissionChecker` uses `os.access()` to verify write/execute/read permissions before attempting operations. |
| **User-level only** | envguard never writes to system directories (no `sudo`). The LaunchAgent is installed to `~/Library/LaunchAgents/`, not `/Library/LaunchAgents/`. |
| **Atomic file writes** | State files use a write-to-tmp-then-rename pattern to prevent corruption. |
| **Restricted file modes** | No explicit chmod operations. Files inherit the user's umask. |

### State file tampering

| Mitigation | Implementation |
|---|---|
| **Schema validation** | JSON files are parsed and validated against expected keys. Malformed files return defaults rather than crashing. |
| **Immutable during pipeline** | `HostFacts` and `ProjectIntent` are treated as immutable snapshots after creation. Normalization happens once at construction. |
| **Checksum on freeze** | Environment freeze snapshots capture the full package list and platform info for audit. |

### Project file parsing

| Mitigation | Implementation |
|---|---|
| **AST-only parsing for setup.py** | `ast.parse()` extracts `install_requires` without executing any code. |
| **Line-by-line requirements parsing** | No eval or exec on requirements.txt lines. Lines starting with `-` or `#` are skipped. |
| **TOML parsing only** | `tomllib`/`tomli` for TOML — no template expansion, no code execution. |
| **Size limits** | Subprocess reads have explicit timeouts; file reads are not bounded but could be added. |

---

## What is NOT guaranteed

envguard's security model has deliberate limitations:

1. **No code signing infrastructure** — Updates are verified by checksum only. There is no GPG signature, no Apple code signing, and no certificate pinning. A compromised release server that serves a correctly-checksummed malicious package would bypass verification.

2. **No TLS certificate pinning** — HTTPS connections use the system's default certificate chain. A compromised CA could MITM the update channel.

3. **No sandboxing** — envguard runs with the user's full permissions. If the user is root, envguard runs as root.

4. **No secret management** — envguard does not handle API keys, tokens, or passwords. Environment variables for authentication are passed through as-is.

5. **No integrity monitoring** — envguard does not monitor its own binary or installed files for tampering between runs.

6. **No audit logging to external systems** — Logs are written to local files only. There is no centralized logging, SIEM integration, or tamper-proof audit trail.

---

## Security assumptions

envguard makes the following assumptions about its operating environment:

1. **Python runtime is trustworthy** — The Python interpreter and standard library are assumed to be correctly installed and not backdoored.

2. **Package managers are trustworthy** — `pip`, `conda`, and other package managers are assumed to correctly install packages from their configured indexes.

3. **HTTPS provides confidentiality and integrity** — TLS connections to PyPI and the update server are assumed to be genuine (no compromised CAs).

4. **User's shell RC files are writable** — Shell integration assumes the user has write access to their own RC files.

5. **macOS security features are functional** — SIP, Gatekeeper, and sandboxing are assumed to be active and functional.

6. **Single-user installation** — envguard is designed for single-user installations. Multi-user security is not a design goal.

---

## Recommendations for production deployment

1. **Pin envguard version** — Use `pip install envguard==<version>` rather than always installing latest.
2. **Review LaunchAgent plist** — Inspect `~/Library/LaunchAgents/com.envguard.update.plist` after installation.
3. **Do not run as root** — envguard is designed for user-level installations.
4. **Audit shell RC changes** — Review `~/.zshrc` or `~/.bashrc` after running `install-shell-hooks`.
5. **Keep Python updated** — envguard's security depends on a correctly patched Python runtime.
6. **Use firewall rules** — If envguard's update checks are not needed, set `channel = "off"` in config to prevent network requests.
7. **Review freeze snapshots** — Periodically inspect `.envguard/snapshots/` for unexpected changes.
