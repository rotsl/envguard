# ADR-0001: macOS-Only Initial Version

**Status:** Accepted
**Date:** 2026-01-15
**Decision makers:** Rohan R

---

## Context

envguard is a Python environment orchestration framework. When designing the initial version, we need to decide the target platform scope. Options include:

1. **macOS-only** — Focus exclusively on macOS (Apple Silicon + Intel).
2. **macOS + Linux** — Support both macOS and Linux from the start.
3. **Cross-platform** — Support macOS, Linux, and Windows from day one.

The decision has significant implications for architecture, testing, and feature availability. macOS-specific features (MPS detection, Rosetta detection, Xcode CLI tools, LaunchAgent integration) are only relevant on macOS. Linux support would require a separate set of platform-specific features (NVIDIA CUDA, apt/brew package detection, systemd services).

---

## Decision

We will target **macOS only** for the initial version (v0.x). Linux is listed in pyproject.toml classifiers as a secondary platform but is not tested or officially supported. Windows is explicitly excluded.

### Rationale

1. **Focused development** — macOS has unique constraints (Apple Silicon, Rosetta 2, Metal Performance Shaders, Xcode CLI tools) that require deep platform integration. Focusing on macOS allows us to solve these problems thoroughly rather than building shallow cross-platform abstractions.

2. **User base alignment** — The primary use case (ML/AI development with Python) heavily overlaps with macOS users who need to manage Apple Silicon vs. Intel compatibility, MPS vs. CPU trade-offs, and wheel architecture issues.

3. **Testing simplicity** — CI can test against a single platform's quirks. Cross-platform testing would require matrix expansion, platform-specific mocking, and conditional behavior in tests.

4. **Apple Silicon complexity** — The arm64/x86_64/Rosetta architecture matrix is already complex enough to warrant focused attention. Adding Linux (which has its own multi-arch story) would dilute this focus.

5. **Feature density** — macOS-specific features (LaunchAgent, shell hooks for zsh/bash, Xcode CLI detection, MPS availability) provide significant value to macOS users. Linux equivalents would be different implementations (systemd timers, apt/dnf, NVIDIA driver detection) with different semantics.

### Linux compatibility notes

While macOS is the primary target, the codebase is written to avoid unnecessary macOS coupling:

- Platform checks use `platform.system() == "Darwin"` rather than assuming macOS.
- macOS-specific modules are isolated in `envguard/macos/`.
- Subprocess calls work on both platforms.
- File system operations use `pathlib.Path` for cross-platform path handling.

This means Linux support could be added incrementally by implementing Linux-specific modules in a future version.

---

## Consequences

### Positive

- **Deep macOS integration** — Features like MPS detection, Rosetta detection, and LaunchAgent integration are first-class.
- **Simpler codebase** — No `if/else` platform branching throughout the code.
- **Clear testing story** — CI matrix is small (Python 3.10/3.11/3.12).
- **Faster development** — No time spent on Linux/Windows edge cases.

### Negative

- **Linux users cannot use envguard** — Until Linux support is added, Linux developers must use alternative tools (pyenv, virtualenvwrapper, conda directly).
- **CI only tests macOS** — Linux-specific bugs in the shared code will not be caught.
- **Community perception** — A macOS-only tool may be seen as niche or exclusionary.

### Mitigations

- The codebase is structured to allow Linux support as a future addition without major refactoring.
- Linux is listed in classifiers to signal future intent.
- Platform-specific code is isolated in `envguard/macos/`, making it easy to add `envguard/linux/` later.

---

## Future considerations

If Linux support is added in a future version, the following changes would be needed:

1. Add `envguard/linux/` module with platform-specific implementations.
2. Add NVIDIA CUDA detection and validation rules.
3. Replace LaunchAgent with systemd timer or cron for auto-updates.
4. Expand CI matrix to include Linux runners.
5. Add `apt`, `dnf`, `pacman` package manager detection.
6. Handle `sudo` requirements for system-level installations.

This ADR should be revisited when planning Linux support.
