# Permissions

This document describes the permission model for envguard on macOS, including what permissions are required, how they are checked, and how permission failures are handled.

---

## Permission model on macOS

envguard is designed to operate **entirely within user-level permissions**. It does not require `sudo`, does not write to system directories, and does not modify files outside the user's home and project directories.

The permission model is based on three principles:

1. **Least privilege** — envguard only requests the minimum permissions needed for each operation.
2. **Check before action** — Permission checks are performed before any write or execution operation, and failures are reported clearly.
3. **User-level only** — No system-level modifications. The LaunchAgent is installed to `~/Library/LaunchAgents/`, not `/Library/LaunchAgents/`.

---

## User-level vs system-level installation

### User-level installation (default and recommended)

```bash
pip install --user envguard
# or
pip install envguard
```

User-level installation places envguard in the user's Python site-packages directory. All operations (state files, cache, snapshots, LaunchAgent) are confined to the user's home directory and project directories.

**Advantages:**
- No `sudo` required
- No risk of affecting other users
- macOS SIP and sandboxing are not involved
- Uninstall is a single `pip uninstall envguard`

### System-level installation (not recommended)

```bash
sudo pip install envguard
```

System-level installation places envguard in `/usr/local/` or the system Python's site-packages. This requires `sudo` and is not tested or officially supported. envguard may encounter permission issues when trying to write state files or cache.

**Problems with system-level:**
- State files in `~/.envguard/` may conflict between users
- Cache files may not be writable by non-root users
- Update mechanism may not be able to modify system-installed files
- Repair operations may fail due to ownership mismatches

---

## Specific permission requirements

### LaunchAgent directory (`~/Library/LaunchAgents/`)

| Operation | Required permission | Checked by |
|---|---|---|
| Install LaunchAgent | Write access to `~/Library/LaunchAgents/` | `PermissionChecker.check_launch_agent_write()` |
| Uninstall LaunchAgent | Write access (to delete the plist file) | `PermissionChecker.check_launch_agent_write()` |
| Load/unload LaunchAgent | `launchctl` must be available and executable | Implicit (command failure handling) |

The LaunchAgent plist is written as `~/Library/LaunchAgents/com.envguard.update.plist`. This directory should always be writable by the user on a standard macOS installation.

### Install directories

| Directory | Required permission | Notes |
|---|---|---|
| `~/.envguard/` | Read + Write | User state directory, created automatically |
| `~/.envguard/cache/` | Read + Write | Update cache, downloaded manifests |
| `~/.envguard/snapshots/` | Read + Write | Rollback snapshots |
| `~/.envguard/logs/` | Read + Write | Log files |
| `~/.envguard/cache/updates/` | Read + Write | Staged update archives |
| `~/.envguard/cache/updates/staging/` | Read + Write | Temporary extraction directory |

These directories are created automatically by `ensure_envguard_dir()` and `UpdateManager.__init__()`. If the home directory is not writable (e.g., on a read-only filesystem), envguard will report a permission error.

### Project directories

| Directory | Required permission | Notes |
|---|---|---|
| `<project>/.envguard/` | Read + Write | Project state, created by `envguard init` |
| `<project>/.envguard/state.json` | Read + Write | Project state file |
| `<project>/.envguard/snapshots/` | Read + Write | Freeze snapshots |
| `<project>/.envguard/cache/` | Read + Write | Project cache |
| `<project>/.envguard/logs/` | Read + Write | Project log files |
| `<project>/.venv/` or `<project>/venv/` | Read + Write | Managed virtual environment |
| `<project>/.conda/` | Read + Write | Managed conda environment |

envguard must have write access to the project directory to create and manage the `.envguard/` subdirectory. If the project directory is read-only, `envguard init` and `envguard repair` will fail with permission errors.

### Shell RC files

| File | Required permission | Notes |
|---|---|---|
| `~/.zshrc` | Write (append) | zsh shell hooks |
| `~/.bashrc` | Write (append) | bash shell hooks |

Shell hooks are installed by **appending** a small block to the RC file. The existing content is never modified or deleted (except during uninstall, where the exact installed block is removed).

envguard checks write permission to the shell RC file before attempting installation via `PermissionChecker.check_shell_rc_write()`.

### Network access

| Operation | Required permission | Notes |
|---|---|---|
| Update checks | Outbound HTTPS to `releases.envguard.dev:443` | TCP socket connection |
| PyPI connectivity | Outbound HTTPS to `pypi.org:443` | TCP socket connection |
| Package downloads | Outbound HTTPS to `files.pythonhosted.org:443` | pip/conda manages this |

envguard does not open listening ports or accept incoming connections. It only makes outbound HTTPS requests for update checks and connectivity tests.

Network access is checked via TCP socket connection (not HTTP request) to minimize dependencies and detect connectivity issues even when DNS is slow.

### Subprocess execution

| Operation | Required permission | Notes |
|---|---|---|
| Run `envguard run -- <cmd>` | Execute permission on the command binary | User must have execute permission |
| Run `python -m venv` | Execute permission on Python binary | Standard Python installation |
| Run `conda create/install` | Execute permission on conda binary | conda must be on PATH |
| Run `pip install` | Execute permission on pip binary | Standard Python installation |
| Run `xcode-select -p` | Execute permission on xcode-select | macOS system tool |

envguard runs all commands as the current user. It never elevates privileges. If a command requires `sudo`, envguard will report a permission error rather than silently running with elevated privileges.

---

## How envguard handles permission failures

### Detection

`PermissionChecker` probes permissions before critical operations:

```python
# Filesystem permission checks
os.access(path, os.W_OK)  # Write
os.access(path, os.R_OK)  # Read
os.access(path, os.X_OK)  # Execute
```

For subprocess and network permissions, actual operations are attempted:

```python
# Subprocess execution check
subprocess.run(["echo", "hello"], capture_output=True, timeout=10)

# Network access check
socket.create_connection(("pypi.org", 443), timeout=5)
```

### Reporting

Permission failures are reported at multiple levels:

1. **In HostFacts** — Permission statuses are stored in the `HostFacts` dataclass:
   - `write_permissions[location]` → `PermissionStatus.GRANTED` or `DENIED`
   - `execute_permissions[binary]` → `PermissionStatus.GRANTED` or `DENIED`
   - `read_permissions[path]` → `PermissionStatus.GRANTED` or `DENIED`
   - `launch_agent_write` → `PermissionStatus.GRANTED` or `DENIED`
   - `subprocess_execution` → `PermissionStatus.GRANTED` or `DENIED`
   - `network_access` → `PermissionStatus.GRANTED` or `DENIED`
   - `shell_rc_write` → `PermissionStatus.GRANTED` or `DENIED`

2. **In diagnostic output** — `envguard doctor` displays permission check results in a table.

3. **As findings** — Permission failures can produce `RuleFinding` objects with severity `WARNING` or `ERROR`.

4. **As exceptions** — Actual permission failures during operations raise `PermissionError` (Python built-in), which is caught and mapped to exit code 5.

### Error messages

Permission failure messages are explicit and actionable:

```
Error: Permission denied: /path/to/file
  → Check file permissions: ls -la /path/to/file
  → Run as the file owner or adjust permissions: chmod u+w /path/to/file
```

### Graceful degradation

Some operations degrade gracefully when permissions are unavailable:

| Scenario | Behavior |
|---|---|
| Cannot write `~/.envguard/cache/` | Update downloads fail; preflight still works |
| Cannot write `~/Library/LaunchAgents/` | LaunchAgent installation fails; CLI still works |
| Cannot write shell RC file | Shell hooks fail to install; CLI still works |
| Cannot write project `.envguard/` | Init and repair fail; doctor and detect still work |
| Cannot execute subprocess | All managed execution fails; detection still works |
| No network access | Update checks and PyPI connectivity fail; local operations work |

---

## Error codes related to permissions

| Exit Code | Constant | When |
|---|---|---|
| 5 | `EXIT_PERMISSION_DENIED` | Any `PermissionError` caught during command execution |
| 1 | `EXIT_GENERAL_ERROR` | Filesystem permission failure mapped to general error |
| 127 | (subprocess) | Command not found (not a permission issue, but related) |

### Common permission-related scenarios

1. **`envguard init` fails with "Permission denied"**
   - Cause: Project directory is not writable.
   - Fix: `chmod u+w <project_dir>` or run from a writable directory.

2. **`envguard install-launch-agent` fails**
   - Cause: `~/Library/LaunchAgents/` does not exist or is not writable.
   - Fix: `mkdir -p ~/Library/LaunchAgents` and check ownership.

3. **`envguard install-shell-hooks` fails**
   - Cause: `~/.zshrc` or `~/.bashrc` is not writable.
   - Fix: `chmod u+w ~/.zshrc` or check file ownership.

4. **`envguard run -- <cmd>` fails with exit code 127**
   - Cause: The command binary is not found on PATH or not executable.
   - Fix: Verify the command exists and is executable: `which <cmd>`.

5. **`envguard update` fails**
   - Cause: Cannot write to `~/.envguard/cache/updates/`.
   - Fix: Ensure home directory is writable and has sufficient disk space.
