# Update Model

This document describes how envguard's self-update mechanism works, including manifest formats, checksum verification, staged updates, rollback, channels, and offline behavior.

---

## Overview

envguard can update itself to newer versions. The update flow is: **check → download → verify → stage → apply → rollback if needed**.

The update system is designed to be:

- **Non-disruptive** — updates are staged in a temporary directory and only applied after full verification.
- **Recoverable** — a rollback snapshot is created before every update.
- **Configurable** — users can choose update channels or disable updates entirely.

---

## How updates work

### The update pipeline

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Check for   │───►│  Download    │───►│  Verify      │
│  updates     │    │  archive     │    │  checksum    │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                                │
                ┌──────────────┐    ┌───────────▼──────┐
                │  Apply       │◄───│  Stage           │
                │  update      │    │  (extract)       │
                └──────┬───────┘    └──────────────────┘
                       │
                ┌──────▼───────┐
                │  Verify      │
                │  post-update │
                └──────────────┘
                       │
                ┌──────▼───────┐
                │  Rollback    │ (if post-update fails)
                │  if needed   │
                └──────────────┘
```

### Step-by-step

1. **Check for updates** — `UpdateManager.check_for_updates()` fetches the remote manifest and compares versions using semver comparison.

2. **Create rollback snapshot** — Before downloading, `RollbackManager.create_snapshot()` saves the current envguard state for potential rollback.

3. **Download** — The update archive (`.tar.gz` or `.zip`) is downloaded to `~/.envguard/cache/updates/`.

4. **Verify** — The downloaded archive's SHA-256 checksum is compared against the manifest's expected checksum. If verification fails, the update is aborted and the archive is deleted.

5. **Stage** — The archive is extracted to `~/.envguard/cache/updates/staging/`. If the staging directory already exists, it is cleaned first.

6. **Apply** — Files from the staging directory are copied over the current envguard installation (located via `importlib.util.find_spec("envguard")`).

7. **Post-update verification** — Not yet implemented in v0.1.0, but designed to run a quick import test after applying.

8. **Rollback** — If any step fails after the snapshot was created, the snapshot can be restored via `envguard rollback <snapshot-id>`.

---

## Manifest format

The remote manifest is a JSON document at `https://releases.envguard.dev/manifest.json` (configurable via `manifest_url` in config).

### Example manifest

```json
{
  "version": "0.2.0",
  "download_url": "https://releases.envguard.dev/envguard-0.2.0.tar.gz",
  "checksum": "a1b2c3d4e5f6...64-character-sha256",
  "checksum_algorithm": "sha256",
  "signature": "",
  "min_python_version": "3.10",
  "platforms": ["darwin"],
  "changelog": "## 0.2.0\n\n### Added\n- Conda backend support\n- LaunchAgent scheduled updates\n\n### Fixed\n- Wheel compatibility for macOS 14",
  "release_date": "2026-07-01",
  "prerelease": false,
  "size_bytes": 524288,
  "package_url": "https://pypi.org/project/envguard/0.2.0/"
}
```

### Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | string | Yes | Semver version string (e.g., `0.2.0`) |
| `download_url` | string | Yes | HTTPS URL to the update archive |
| `checksum` | string | Yes | Hex-encoded SHA-256 hash of the archive |
| `checksum_algorithm` | string | Yes | Hash algorithm (`sha256`, `sha384`, `sha512`) |
| `signature` | string | No | Reserved for future code signing |
| `min_python_version` | string | No | Minimum Python version required (e.g., `3.10`) |
| `platforms` | list[string] | No | Target platforms (e.g., `["darwin", "linux"]`) |
| `changelog` | string | No | Markdown changelog for display |
| `release_date` | string | No | ISO 8601 release date |
| `prerelease` | boolean | No | Whether this is a pre-release version |
| `size_bytes` | integer | No | Expected download size in bytes |
| `package_url` | string | No | URL to the PyPI package page |

### Validation rules

The `ManifestParser.validate()` method checks:

- `version` matches semver pattern (`MAJOR.MINOR.PATCH`)
- `download_url` starts with `http://` or `https://`
- `checksum` is non-empty
- `checksum_algorithm` is one of `sha256`, `sha384`, `sha512`, `md5`
- `platforms` is a non-empty list if present
- `min_python_version` is a valid version string if present
- `size_bytes` is non-negative if present
- `release_date` is a valid ISO 8601 string if present

---

## Checksum verification (SHA-256)

All update verification uses SHA-256 by default. The `SignatureVerifier` class in `security/signatures.py` provides:

- **Chunked file hashing** — Files are read in 64KB chunks to handle large archives without loading them entirely into memory.
- **Hash normalization** — Expected hashes are stripped of whitespace, `0x` prefixes, and lowercased before comparison.
- **Explicit failure** — On mismatch, a `VerificationError` is raised with both the expected and computed hashes in the message.

```python
# Simplified flow
computed = sha256(download_path)
expected = manifest.checksum
if computed != expected:
    raise VerificationError(...)
```

The hash computation is:

```python
hasher = hashlib.new("sha256")
with open(file_path, "rb") as fh:
    while chunk := fh.read(65536):
        hasher.update(chunk)
digest = hasher.hexdigest()
```

---

## Staged updates

Updates follow a staged approach to minimize the window of broken state:

1. **Download to cache** — The archive is saved to `~/.envguard/cache/updates/<filename>`.
2. **Extract to staging** — The archive is extracted to `~/.envguard/cache/updates/staging/`. If staging already exists from a previous failed update, it is cleaned with `shutil.rmtree()`.
3. **Verify in staging** — Checksum verification happens on the downloaded archive file, before extraction.
4. **Copy to install location** — Files from `staging/src/envguard/` (or `staging/envguard/`) are copied over the current installation directory.
5. **Staging cleanup** — The staging directory is left in place after a successful update (it will be cleaned on the next update). This allows inspection if something goes wrong.

### Supported archive formats

| Format | Extension | Method |
|---|---|---|
| ZIP | `.zip` | `zipfile.ZipFile.extractall()` |
| Gzip tarball | `.tar.gz`, `.tgz` | `tarfile.open(mode="r:gz")` |
| Single file | (fallback) | `shutil.copy2()` |

---

## Rollback mechanism

### Snapshots

Before every update, `RollbackManager.create_snapshot()` saves a snapshot identified by a unique ID (timestamp-based). Snapshots are stored as JSON files in `~/.envguard/snapshots/`.

### Listing available snapshots

```bash
envguard rollback
```

This displays a table of all available snapshots with their IDs and file paths.

### Rolling back

```bash
envguard rollback <snapshot-id>
```

This restores the envguard installation to the state captured in the snapshot. The rollback operation:

1. Reads the snapshot data from `~/.envguard/snapshots/<snapshot-id>.json`.
2. Determines the original installation path.
3. Copies the snapshot files over the current installation.

### Snapshot contents

Snapshots capture:

- Timestamp of the snapshot
- Version of envguard at snapshot time
- Description (e.g., "Before update to v0.2.0")
- Reference to the backup files (implementation varies by version)

### Limitations

- Rollback does not restore the Python environment or dependencies — only the envguard package itself.
- If envguard is completely broken (cannot import), rollback from the CLI may not work. Manual reinstallation via `pip install envguard==<version>` is the fallback.
- Snapshots are stored indefinitely unless manually cleaned.

---

## Channels

The update channel is configured in `config/default.toml` or `.envguard/envguard.toml`:

| Channel | Behavior |
|---|---|
| `stable` | Only stable releases. Default. |
| `beta` | Includes pre-release versions. |
| `off` | Disables automatic update checks. Manual updates still work. |

```toml
[update]
channel = "stable"  # stable, beta, off
auto_check = true
check_interval_hours = 24
dry_run = false
```

The `dry_run` option checks for updates without installing them, which is useful for the LaunchAgent (which should check but not install without user interaction).

---

## LaunchAgent integration

The optional LaunchAgent (`com.envguard.update.plist`) schedules periodic update checks. By default, it runs `envguard update --dry-run` every 24 hours.

The LaunchAgent:

- **Only checks** — It does not install updates automatically. It runs in dry-run mode.
- **Logs to stdout/stderr** — Captured by launchd and viewable via `log show --predicate 'process == "envguard"'`.
- **User-level** — Installed to `~/Library/LaunchAgents/`, not system-wide.

To install: `envguard install-launch-agent`
To uninstall: `envguard uninstall-launch-agent`
To load immediately: `launchctl load -w ~/Library/LaunchAgents/com.envguard.update.plist`

---

## Offline behavior

When network is unavailable, envguard's update system behaves as follows:

| Operation | Behavior |
|---|---|
| `envguard update` | Returns error: "Failed to fetch manifest" |
| `envguard update --dry-run` | Same — cannot check without network |
| LaunchAgent | Silently fails (logged as warning) |
| `envguard rollback <id>` | Works offline — uses local snapshots |
| `envguard run -- <cmd>` | Works offline if environment is already set up |

envguard detects network unavailability during preflight (via TCP socket to `pypi.org:443`) and produces a `WARNING` finding when the project requires network access for package downloads.

---

## What is NOT guaranteed about update security

1. **No code signing** — Updates are verified by checksum only. There is no GPG signature verification, no Apple code signing validation. A compromised release server that correctly hashes a malicious package would bypass verification.

2. **No certificate pinning** — HTTPS connections to the manifest server use the system's default trust store. A compromised certificate authority could enable MITM attacks.

3. **No integrity monitoring between runs** — envguard does not check whether its own files have been tampered with since the last update.

4. **No reproducible builds** — There is no mechanism to verify that the published archive matches a source-level build.

5. **Manifest server availability** — If `releases.envguard.dev` is unreachable, update checks fail. There is no mirror or fallback URL mechanism.
