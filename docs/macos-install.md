# macOS Installation Guide

This document provides detailed installation instructions for envguard on macOS, covering both Apple Silicon and Intel Macs.

---

## Prerequisites

### Python 3.10+

envguard requires Python 3.10 or later. Check your current version:

```bash
python3 --version
```

If you need to install or upgrade Python:

**Apple Silicon (arm64):**
```bash
brew install python@3.12
```

**Intel (x86_64):**
```bash
brew install python@3.12
```

**Via pyenv (either architecture):**
```bash
brew install pyenv
pyenv install 3.12
pyenv global 3.12
```

**Via conda:**
```bash
conda create -n envguard python=3.12
conda activate envguard
```

### Xcode Command Line Tools

Xcode Command Line Tools are required for building native extensions (Cython, CFFI, pybind11, setuptools-rust) and are strongly recommended for all envguard users.

```bash
xcode-select --install
```

This opens a dialog to download and install the tools. After installation, verify:

```bash
xcode-select -p
# Output: /Library/Developer/CommandLineTools
```

If you already have Xcode installed (full IDE), the Command Line Tools are included. Accept the license if prompted:

```bash
sudo xcodebuild -license accept
```

### pip

pip is required for installation. It is included with Python on most installations:

```bash
python3 -m pip --version
```

If pip is not available:

```bash
python3 -m ensurepip --upgrade
```

---

## User-level install (recommended)

Install envguard into your user's Python environment:

```bash
pip install envguard
```

Or with `--user` flag for explicit user-level installation:

```bash
pip install --user envguard
```

### Verify installation

```bash
envguard --help
envguard doctor
```

`envguard doctor` runs 10 diagnostic checks and confirms that envguard is correctly installed and functional on your system.

### Installation location

User-level installations place envguard in one of these locations, depending on your Python setup:

| Python source | envguard location |
|---|---|
| Homebrew Python | `/opt/homebrew/lib/python3.12/site-packages/envguard/` (Apple Silicon) or `/usr/local/lib/python3.12/site-packages/envguard/` (Intel) |
| pyenv Python | `~/.pyenv/versions/3.12.x/lib/python3.12/site-packages/envguard/` |
| conda Python | `$CONDA_PREFIX/lib/python3.12/site-packages/envguard/` |
| System Python | `/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/site-packages/envguard/` |

---

## System-level install (requires sudo)

System-level installation is **not recommended**. It requires sudo and may cause permission issues. Use this only if you have a specific need for system-wide availability.

```bash
sudo pip install envguard
```

### Problems with system-level install

- State files in `~/.envguard/` may have ownership conflicts if created by root.
- Updates may fail because the update mechanism writes to the system site-packages directory.
- Multiple users on the same machine will share the same installation but have separate state directories.

### If you must use system-level

After installation, fix the cache directory ownership:

```bash
sudo mkdir -p ~/.envguard/cache ~/.envguard/snapshots ~/.envguard/logs
sudo chown -R $(whoami) ~/.envguard
```

---

## Installing shell hooks

Shell hooks are optional and provide envguard completions on shell startup.

```bash
envguard install-shell-hooks
```

This detects your shell (zsh or bash) and appends a small block to the corresponding RC file:

- zsh: `~/.zshrc`
- bash: `~/.bashrc`

The installed block:

```bash
# envguard shell integration
# Source envguard completions and env activation
if command -v envguard &> /dev/null; then
    eval "$(envguard _completion)" 2>/dev/null || true
fi
```

After installation, reload your shell:

```bash
source ~/.zshrc  # or source ~/.bashrc
```

### To uninstall shell hooks

```bash
envguard uninstall-shell-hooks
```

This removes the exact block that was installed. It does not modify any other content in your RC file.

### Specify a shell explicitly

```bash
envguard install-shell-hooks --shell zsh
envguard install-shell-hooks --shell bash
```

---

## Installing LaunchAgent

The LaunchAgent enables periodic update checks (every 24 hours by default).

```bash
envguard install-launch-agent
```

This creates `~/Library/LaunchAgents/com.envguard.update.plist`. To activate it immediately:

```bash
launchctl load -w ~/Library/LaunchAgents/com.envguard.update.plist
```

The LaunchAgent runs `envguard update --dry-run` on a schedule. It does **not** install updates automatically — it only checks for them.

### To verify the LaunchAgent is loaded

```bash
launchctl list | grep envguard
```

### To view LaunchAgent logs

```bash
log show --predicate 'process == "envguard"' --last 1h
```

### To unload and uninstall the LaunchAgent

```bash
envguard uninstall-launch-agent
```

This both unloads the LaunchAgent from launchd and deletes the plist file.

---

## Uninstallation

### Remove envguard

```bash
pip uninstall envguard
```

### Remove shell hooks

```bash
envguard uninstall-shell-hooks
```

### Remove LaunchAgent

```bash
envguard uninstall-launch-agent
```

### Remove user-level state

```bash
rm -rf ~/.envguard
```

### Remove project-level state

For each project where envguard was initialized:

```bash
rm -rf /path/to/project/.envguard
```

### Complete cleanup

```bash
pip uninstall envguard
envguard uninstall-shell-hooks 2>/dev/null || true
envguard uninstall-launch-agent 2>/dev/null || true
rm -rf ~/.envguard
```

Note: The `uninstall-shell-hooks` and `uninstall-launch-agent` commands may fail if envguard is already uninstalled (since the CLI is gone). In that case, manually remove the relevant sections from `~/.zshrc`/`~/.bashrc` and delete `~/Library/LaunchAgents/com.envguard.update.plist`.

---

## Troubleshooting installation issues

### "command not found: envguard"

The envguard binary is not on your PATH. Check your Python's script directory:

```bash
python3 -m site --user-base
```

Ensure the `bin` directory under that path is in your PATH. Add to your shell RC:

```bash
export PATH="$(python3 -m site --user-base)/bin:$PATH"
```

### "Permission denied" during pip install

Use `--user` flag:

```bash
pip install --user envguard
```

Or use a virtual environment:

```bash
python3 -m venv ~/envguard-venv
source ~/envguard-venv/bin/activate
pip install envguard
```

### "SSL: CERTIFICATE_VERIFY_FAILED" during pip install

macOS Python installations may have certificate issues. Fix:

```bash
# Install certificates from macOS
/Applications/Python\ 3.12/Install\ Certificates.command

# Or set pip to use system certificates
export REQUESTS_CA_BUNDLE=/etc/ssl/cert.pem
pip install envguard
```

### "xcode-select: error" during doctor checks

Install Xcode Command Line Tools:

```bash
xcode-select --install
```

If it fails with "xcode-select: error: tool 'xcode-select' requires Xcode", you may need to accept the license:

```bash
sudo xcodebuild -license accept
```

### envguard doctor shows network failures behind proxy

Set proxy environment variables:

```bash
export HTTPS_PROXY=http://proxy.example.com:8080
export HTTP_PROXY=http://proxy.example.com:8080
envguard doctor
```

---

## Apple Silicon specific notes

### Native arm64 vs Rosetta 2

Apple Silicon Macs can run both arm64 (native) and x86_64 (via Rosetta 2) Python. **Always use the native arm64 Python** for best performance and wheel compatibility.

Check your Python architecture:

```bash
python3 -c "import platform; print(platform.machine())"
# Should output: arm64
```

If it outputs `x86_64`, your Python is running under Rosetta 2. envguard will detect this and produce a `WARNING` finding about Rosetta translation.

### Install native arm64 Python

```bash
brew install python@3.12
```

Homebrew installs arm64-native Python on Apple Silicon by default.

### Terminal.app Rosetta setting

Ensure Terminal.app (or iTerm2) is not running in Rosetta mode:

1. Open Finder → Applications → Utilities → Terminal
2. Right-click → Get Info
3. Ensure "Open using Rosetta" is **unchecked**

### MPS (Metal Performance Shaders)

MPS requires macOS 12.3 (Monterey) or later on Apple Silicon. Check availability:

```bash
python3 -c "import torch; print(torch.backends.mps.is_available())"
# Requires PyTorch installed
```

envguard detects MPS availability based on macOS version (12.3+) and architecture (arm64).

### Wheel compatibility

Most popular Python packages now ship arm64 wheels for macOS. However, some packages may only have x86_64 or universal2 wheels. envguard's wheel compatibility check queries PyPI to verify arm64 wheel availability for architecture-sensitive packages.

---

## Intel Mac notes

### x86_64 is the native architecture

Intel Macs use x86_64 natively. All Python wheels for macOS/x86_64 should work without issues.

### No Rosetta concerns

Intel Macs do not use Rosetta 2 (Rosetta 2 is for running x86_64 binaries on arm64 hardware, not the reverse). envguard's Rosetta detection will correctly report `is_rosetta: false` on Intel Macs.

### Older macOS versions

envguard requires macOS 12.0 (Monterey) or later. On older versions:

- `envguard doctor` will report a platform compatibility warning.
- Some features (MPS, modern PyTorch) may not be available.
- Xcode CLI tools may require an older version of Xcode.

### Upgrading from Intel to Apple Silicon

If you migrate an Intel Mac project to an Apple Silicon Mac:

1. Run `envguard doctor` to detect architecture mismatches.
2. Reinstall your Python environment with native arm64 Python.
3. Run `envguard repair` to recreate the environment with correct architecture.

---

## Rosetta considerations

### What Rosetta 2 does

Rosetta 2 is Apple's dynamic binary translation layer that allows x86_64 applications to run on Apple Silicon (arm64) hardware. It works transparently but has trade-offs:

- **Performance**: Some operations are slower under Rosetta (typically 10-30% overhead, but native extension code can be much slower).
- **Wheel compatibility**: x86_64 Python under Rosetta will download x86_64 wheels, which may not be optimized for Apple Silicon.
- **Mixed environments**: Mixing arm64 and x86_64 Python on the same machine can cause confusion.

### envguard Rosetta detection

envguard detects Rosetta translation via `sysctl -n sysctl.proc_translated`:

```python
result = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], capture_output=True)
is_rosetta = result.stdout.strip() == "1"
```

When Rosetta is detected:

1. A `WARNING` finding (`ROSETTA_TRANSLATION_DETECTED`) is produced.
2. The recommendation is to install native arm64 Python via Homebrew.
3. Managed execution continues but with the warning.

### Fixing Rosetta issues

```bash
# Install native arm64 Python
brew install python@3.12

# Verify it's arm64
/opt/homebrew/bin/python3 -c "import platform; print(platform.machine())"
# Output: arm64

# Recreate your environment
rm -rf .venv
/opt/homebrew/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
