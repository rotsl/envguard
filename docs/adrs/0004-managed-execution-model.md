# ADR-0004: Managed Execution Model

**Status:** Accepted
**Date:** 2026-01-15
**Decision makers:** Rohan R

---

## Context

envguard's core value proposition is ensuring that Python environments are correct before code runs. The question is: **how should envguard enforce this guarantee?**

### Options

1. **Advisory mode** — envguard provides diagnostic information (`doctor`, `detect`, `preflight`) but does not intercept or control execution. Users run their commands directly and consult envguard separately.

2. **Managed execution** — envguard wraps command execution with `envguard run -- <command>`. Every managed run is preceded by preflight checks. If checks fail, execution is blocked.

3. **System-level interception** — envguard intercepts all Python invocations system-wide (e.g., via shell function, PATH manipulation, or kernel-level hooking). Every `python` command goes through envguard.

4. **IDE integration** — envguard integrates with IDEs (VS Code, PyCharm) to provide preflight checks in the IDE's run configuration.

---

## Decision

We will use **managed execution** (option 2) as the core guarantee. envguard provides `envguard run -- <command>` as the primary execution entry point. Preflight checks run before every managed execution. Shell hooks provide convenience integration, and system-level interception is explicitly out of scope.

### Implementation

The `envguard run` command:

1. Resolves the project directory.
2. Runs the full preflight pipeline (unless `--no-preflight` is specified).
3. Detects the active environment (`.venv`, `CONDA_PREFIX`).
4. Prepends the environment's `bin/` directory to `PATH`.
5. Sets `VIRTUAL_ENV` or `CONDA_PREFIX` environment variables.
6. Executes the command as a subprocess in the project directory.
7. Returns the subprocess exit code.

### Rationale

1. **Explicit consent** — Users opt into preflight by using `envguard run`. There is no surprise interception. Commands run outside envguard continue to work as before.

2. **Composable** — `envguard run` can be used in shell scripts, Makefiles, CI/CD pipelines, and alias definitions. It does not require special shell configuration or daemon processes.

3. **No system-wide side effects** — envguard does not modify `PATH`, shell functions, or system configuration to intercept commands. This avoids conflicts with other tools and makes uninstallation clean.

4. **Clear failure modes** — When preflight fails, envguard exits with code 2 and a clear error message. The user knows exactly why execution was blocked and can fix the issue or use `--no-preflight` to override.

5. **Auditability** — Every managed run is logged. The preflight result includes host facts, findings, and resolution data. This provides an audit trail for debugging and compliance.

### Why not system-level interception?

System-level interception (option 3) would provide stronger guarantees but has significant drawbacks:

- **Shell function wrapping** (`python() { envguard run -- python "$@"; }`) is fragile, breaks in subshells, and conflicts with other wrappers.
- **PATH manipulation** (placing an envguard shim before the real `python`) can break tools that inspect `sys.executable` or expect the real Python binary.
- **Kernel-level hooking** is not possible without privileged code (SIP prevents this on macOS).
- **Surprise behavior** — Users who don't understand why their `python` command is behaving differently will have a poor experience.
- **Uninstall complexity** — Removing system-level hooks requires careful cleanup of shell configurations.

### Why not advisory mode only?

Advisory mode (option 1) is useful for diagnostics but does not prevent environment issues. Users can read the output of `envguard doctor` but still forget to fix the issues before running their code. The managed execution model closes the loop between detection and action.

### Why not IDE integration?

IDE integration (option 4) is valuable but limited to specific IDEs. Managed execution is IDE-agnostic: any IDE that allows configuring the run command can use `envguard run`. We provide managed execution as the universal mechanism and leave IDE-specific integration as a future enhancement.

---

## Consequences

### Positive

- **Strong guarantee** — When using `envguard run`, preflight is guaranteed to run before every execution.
- **No side effects** — envguard does not modify the user's shell, PATH, or system configuration.
- **Explicit control** — Users can bypass preflight with `--no-preflight` when they know it's safe.
- **Portable** — Works in shell scripts, Makefiles, CI/CD, and manual terminal usage.

### Negative

- **Requires explicit adoption** — Users must change their workflow from `python script.py` to `envguard run -- python script.py`. This is an adoption barrier.
- **Does not catch unmanaged execution** — If a user runs `python script.py` directly (without envguard), no preflight checks run. envguard cannot prevent this.
- **Per-command overhead** — Preflight takes a few seconds (network check, rules evaluation, environment validation). This adds latency to every managed run.

### Mitigations

- **Shell aliases** — Users can define `alias run="envguard run --"` for convenience.
- **CI/CD integration** — In CI pipelines, preflight overhead is acceptable and provides value.
- **`--no-preflight` escape hatch** — For hot loops or performance-sensitive workflows, users can skip preflight.
- **Documentation** — Clear documentation on when and how to use managed execution.

---

## Design principle: honesty about guarantees

envguard's managed execution model comes with an explicit honesty policy:

> envguard only guarantees preflight for managed entry points. If you don't use `envguard run`, envguard cannot help you.

This is stated in the README, documentation, and CLI help text. We do not overstate our capabilities or imply that envguard controls all Python execution on the system.

---

## Future considerations

1. **`direnv` integration** — A `direnv` hook could automatically run `envguard preflight` when entering a project directory, providing semi-managed execution without requiring `envguard run`.

2. **IDE plugins** — VS Code and PyCharm plugins could configure `envguard run` as the default Python runner.

3. **Preflight caching** — Cache preflight results and only re-run when project files or system state change. This would reduce the per-command overhead.

4. **`source envguard activate`** — An activation script that wraps `source venv/bin/activate` with preflight checks, providing a more natural workflow for users accustomed to virtual environment activation.

---

## Related

- ADR-0001: macOS-Only Initial Version — Platform scope
- ADR-0002: No CUDA on macOS — Specific preflight rule
- [docs/architecture.md](../architecture.md) — Core pipeline and data flow
- [docs/limitations.md](../limitations.md) — Cannot control unmanaged process launches
