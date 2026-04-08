# Troubleshooting

Common issues and solutions when using envguard on macOS.

---

## "CUDA not supported on macOS"

### Symptom

```
[CIRITICAL] CUDA_ON_MACOS: CUDA is not supported as a runtime target on macOS
  → Use CPU or Apple MPS (Metal Performance Shaders) instead
```

### Cause

Your project depends on CUDA-related packages (torch, tensorflow, jax, nvidia, cuda) but you are running on macOS, which does not have NVIDIA GPUs or CUDA support.

### Solution

1. **Switch to MPS** (Apple Silicon only, macOS 12.3+):
   ```python
   # PyTorch
   import torch
   device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
   ```

2. **Switch to CPU** (universal fallback):
   ```python
   device = torch.device("cpu")
   ```

3. **Remove CUDA dependencies** from your requirements:
   ```
   # Remove these:
   nvidia-cublas-cu11
   nvidia-cuda-nvrtc-cu11
   torch==2.0.0+cu118  # CUDA-specific wheel
   ```

4. **Install the correct PyTorch** for macOS:
   ```bash
   pip install torch torchvision torchaudio
   ```

### Related

- See [ADR-0002: No CUDA on macOS](adrs/0002-no-cuda-on-macos.md) for the architectural decision.
- See [docs/limitations.md](limitations.md) for the full list of GPU limitations.

---

## "Permission denied" errors

### Symptom

```
[bold red]Error:[/bold red] [Errno 13] Permission denied: '/path/to/file'
Exit code: 5
```

### Common causes and fixes

#### Project directory not writable

```bash
# Check permissions
ls -la /path/to/project

# Fix: change ownership
sudo chown -R $(whoami) /path/to/project

# Fix: add write permission
chmod u+w /path/to/project
```

#### Home directory not writable

```bash
# Check
ls -la ~

# Fix
sudo chown -R $(whoami) ~
```

#### LaunchAgent directory not writable

```bash
# Create if missing
mkdir -p ~/Library/LaunchAgents

# Check ownership
ls -la ~/Library/LaunchAgents

# Fix
sudo chown $(whoami) ~/Library/LaunchAgents
```

#### Shell RC file not writable

```bash
# Check
ls -la ~/.zshrc

# Fix
chmod u+w ~/.zshrc
```

---

## "Network unavailable" errors

### Symptom

```
[WARNING] NETWORK_UNAVAILABLE: Network access appears to be unavailable.
  → Check your internet connection. If behind a proxy, set HTTPS_PROXY / HTTP_PROXY.
```

### Causes

1. No internet connection
2. Firewall blocking outbound HTTPS
3. Corporate proxy requiring authentication
4. DNS resolution failure

### Solutions

#### Check connectivity

```bash
# Test HTTPS to PyPI
curl -I https://pypi.org

# Test DNS resolution
nslookup pypi.org

# Test TCP connection
nc -zv pypi.org 443
```

#### Set proxy environment variables

```bash
export HTTPS_PROXY=http://proxy.example.com:8080
export HTTP_PROXY=http://proxy.example.com:8080

# Verify
envguard doctor
```

#### Add proxy to shell RC file (persistent)

```bash
echo 'export HTTPS_PROXY=http://proxy.example.com:8080' >> ~/.zshrc
source ~/.zshrc
```

#### Disable update checks if offline

Add to `.envguard/envguard.toml`:

```toml
[update]
channel = "off"
auto_check = false
```

---

## Mixed pip/conda issues

### Symptom

```
[WARNING] MIXED_PIP_CONDA_OWNERSHIP: Packages installed by both pip and conda:
  numpy, scipy, pandas
  → Reinstall conflicting packages using only conda.
```

### Cause

You installed some packages with `pip install` inside a conda environment. Conda tracks package ownership via `conda-meta/` directory. When pip installs packages that conda also manages, both tools may overwrite each other's metadata, leading to import errors and environment corruption.

### Solutions

#### Automatic fix

```bash
envguard repair
```

The repair engine will detect mixed ownership and attempt to fix it via `conda-unpack` or selective reinstallation.

#### Manual fix

```bash
# 1. Export pip packages
pip freeze > /tmp/pip_backup.txt

# 2. Uninstall all pip packages
pip uninstall -y -r /tmp/pip_backup.txt

# 3. Reinstall conda-available packages via conda
conda install numpy scipy pandas

# 4. Reinstall pip-only packages with --no-deps
pip install --no-deps <package1> <package2>
```

#### Prevention

Always use `conda install` for packages available in conda channels. Only use `pip install` for packages not available in conda.

```bash
# Good: use conda for available packages
conda install numpy scipy pandas matplotlib

# OK: use pip for conda-unavailable packages
pip install some-rare-package
```

---

## Wheel incompatibility on Apple Silicon

### Symptom

```
[WARNING] INCOMPATIBLE_WHEEL: The following packages may not have compatible arm64 wheels:
  torch, numpy, opencv-python
  → Consider building from source or using universal2 wheels.
```

### Cause

Some packages do not ship arm64 (Apple Silicon) wheels for macOS. The package may only have x86_64 wheels, requiring Rosetta 2 translation or source compilation.

### Solutions

#### Install Xcode Command Line Tools (for source builds)

```bash
xcode-select --install
```

#### Use universal2 wheels

```bash
# Check if a universal2 wheel exists
pip index versions <package> --pre --format json | python -m json.tool

# Force universal2 wheel
pip install <package> --only-binary=:all: --platform macosx_11_0_universal2
```

#### Install native arm64 Python

```bash
brew install python@3.12
```

Ensure you're using the Homebrew Python, not the system Python or Rosetta-translated Python:

```bash
# Check architecture
python3 -c "import platform; print(platform.machine())"
# Should be: arm64
```

#### Build from source

```bash
pip install <package> --no-binary <package>
```

This forces pip to compile the package from source, which will produce a native arm64 wheel if Xcode CLI tools are installed.

### Known problematic packages

| Package | Notes |
|---|---|
| `opencv-python` | Has arm64 wheels since 4.7+. Use `opencv-python-headless` for servers. |
| `torch` | Has arm64 wheels for macOS 12+. Install via `pip install torch`. |
| `numpy` | Has arm64 wheels since 1.21+. Use `pip install numpy --upgrade`. |
| `scipy` | Has arm64 wheels since 1.7+. May require source build on older versions. |
| `psutil` | Has arm64 wheels. Requires source build if wheel not found. |
| `cryptography` | Has arm64 wheels. Requires Rust compiler for source builds. |
| `grpcio` | Large package; arm64 wheels available but may take time to build. |

---

## Rosetta-related problems

### Symptom

```
[WARNING] ROSETTA_TRANSLATION_DETECTED: Python is running under Rosetta 2 translation
  (x86_64 on arm64 host).
```

### Cause

Your Python interpreter is x86_64 running under Rosetta 2 on an Apple Silicon Mac. This happens when:

1. Terminal.app has "Open using Rosetta" enabled.
2. You installed x86_64 Homebrew (`/usr/local/bin/brew` instead of `/opt/homebrew/bin/brew`).
3. Your shell is launched under Rosetta.

### Solutions

#### Fix Terminal.app

1. Finder → Applications → Utilities → Terminal
2. Right-click → Get Info
3. Uncheck "Open using Rosetta"
4. Restart Terminal

#### Install native arm64 Homebrew

```bash
# Check current Homebrew architecture
file $(which brew)

# If x86_64, reinstall for arm64:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### Install native arm64 Python

```bash
brew install python@3.12
/opt/homebrew/bin/python3 -c "import platform; print(platform.machine())"
# Output: arm64
```

#### Force arm64 execution

```bash
arch -arm64 python3 -c "import platform; print(platform.machine())"
```

---

## Shell hooks not working

### Symptom

Shell hooks were installed but completions or environment activation is not working.

### Solutions

#### Reload shell RC file

```bash
source ~/.zshrc   # or source ~/.bashrc
```

#### Verify hooks are installed

```bash
# Check zsh
grep "envguard shell integration" ~/.zshrc

# Check bash
grep "envguard shell integration" ~/.bashrc
```

#### Check envguard is on PATH

```bash
which envguard
echo $PATH
```

If envguard is not found, add its directory to PATH:

```bash
export PATH="$(python3 -m site --user-base)/bin:$PATH"
```

#### Check for syntax errors in RC file

```bash
# zsh
zsh -n ~/.zshrc

# bash
bash -n ~/.bashrc
```

---

## LaunchAgent not running

### Symptom

```bash
envguard install-launch-agent
# No errors, but updates are not being checked
```

### Solutions

#### Load the LaunchAgent manually

```bash
launchctl load -w ~/Library/LaunchAgents/com.envguard.update.plist
```

#### Check if loaded

```bash
launchctl list | grep envguard
```

#### View LaunchAgent logs

```bash
log show --predicate 'process == "envguard"' --last 24h
```

#### Check the plist file

```bash
cat ~/Library/LaunchAgents/com.envguard.update.plist
```

Verify that:
- The `ProgramArguments` array points to a valid `envguard` binary.
- The `StartInterval` is set to the desired interval (default: 86400 seconds = 24 hours).
- The `WorkingDirectory` exists and is writable.

#### Unload and reinstall

```bash
envguard uninstall-launch-agent
envguard install-launch-agent
launchctl load -w ~/Library/LaunchAgents/com.envguard.update.plist
```

---

## Environment corruption

### Symptom

```
[ERROR] BROKEN_ENVIRONMENT: Environment exists at '.venv' but appears to be broken
  (no Python binary).
```

### Cause

The virtual environment's Python binary was deleted, the environment directory was partially removed, or the Python installation that created the environment was uninstalled.

### Solutions

#### Automatic repair

```bash
envguard repair
```

This will detect the broken environment and recreate it.

#### Manual recreation

```bash
# Remove the broken environment
rm -rf .venv

# Recreate
python3 -m venv .venv

# Install dependencies
source .venv/bin/activate
pip install -r requirements.txt
```

#### Restore from backup

If envguard created a backup before the environment broke:

```bash
ls .envguard/backups/
# Find the latest backup
ls -lt .envguard/backups/
```

---

## Python version mismatches

### Symptom

```
[ERROR] PYTHON_VERSION_MISMATCH: Python version mismatch: project requires >=3.11
  but host has 3.10.
```

### Cause

The project specifies a minimum Python version (in `pyproject.toml`, `.python-version`, or `requires-python`) that is higher than the Python version currently in use.

### Solutions

#### Install the required version

```bash
# Via Homebrew
brew install python@3.11

# Via pyenv
pyenv install 3.11
pyenv local 3.11

# Via conda
conda create -n myproject python=3.11
conda activate myproject
```

#### Update the project's Python version requirement

If you want to use the currently installed Python:

```toml
# pyproject.toml
[project]
requires-python = ">=3.10"
```

```
# .python-version
3.10
```

#### Recreate the environment with the correct Python

```bash
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
