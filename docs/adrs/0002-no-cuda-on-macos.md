# ADR-0002: No CUDA on macOS

**Status:** Accepted
**Date:** 2026-01-15
**Decision makers:** Rohan R

---

## Context

macOS does not support NVIDIA CUDA. Apple Silicon hardware uses Apple's own GPU architecture, and Intel Macs use integrated Intel GPUs. There is no NVIDIA GPU in any currently shipping Mac.

However, many Python ML/AI projects list CUDA-dependent packages in their requirements (e.g., `torch` with CUDA-specific wheels like `torch==2.0.0+cu118`, `nvidia-cublas-cu11`, `tensorflow-gpu`). When these projects are cloned to a Mac, naive `pip install -r requirements.txt` will either fail or install incompatible x86_64 wheels.

envguard needs a policy for handling CUDA dependencies on macOS.

### Options

1. **Silently ignore CUDA** — Don't check for CUDA requirements. Let `pip install` fail naturally.
2. **Warn about CUDA** — Detect CUDA dependencies and produce a warning finding.
3. **Error on CUDA** — Detect CUDA dependencies and produce a critical finding that blocks execution.
4. **Auto-substitute MPS** — Detect CUDA dependencies and automatically rewrite them to use MPS or CPU equivalents.

---

## Decision

We will **error on CUDA** (option 3) with a recommendation to use MPS or CPU as alternatives. This is implemented as the `CUDA_ON_MACOS` rule in `RulesEngine`, which produces a `CRITICAL` severity finding when CUDA is required on macOS.

### Implementation

The `check_cuda_on_macos()` rule fires when:

1. The host is macOS (`os_name == "Darwin"`).
2. AND any of these conditions are true:
   - `ProjectIntent.requires_cuda` is `True`
   - `ProjectIntent.has_cuda_requirements` is `True`
   - `ProjectIntent.accelerator_target == AcceleratorTarget.CUDA`

CUDA dependencies are detected by scanning project dependency lists for keywords: `torch`, `tensorflow`, `jax`, `cuda`, `nvidia`.

### Rationale

1. **Prevent cryptic errors** — A CUDA dependency on macOS will fail at import time with obscure error messages like "RuntimeError: CUDA not available" or "OSError: dlopen: cannot load CUDA libraries." Catching this at preflight time provides a clear, actionable error message.

2. **Honest about hardware** — envguard should not pretend that CUDA works on macOS. It doesn't, and it won't, because Apple does not ship NVIDIA GPUs.

3. **Guide users to alternatives** — The critical finding includes a remediation suggestion: "Use CPU or Apple MPS (Metal Performance Shaders) instead."

4. **Block before install** — By catching CUDA dependencies at preflight time (before `pip install`), envguard prevents wasted time downloading and installing incompatible packages.

5. **Auto-substitution is too risky** — Automatically rewriting `torch==2.0.0+cu118` to `torch==2.0.0` could change semantics (some projects rely on CUDA-specific behavior). The user should make this decision explicitly.

### Why not warn instead of error?

A warning (option 2) would allow execution to proceed, which would likely fail at import time anyway. The error (option 3) catches the issue earlier and more clearly. Users who want to override this can use `--no-preflight` or `envguard run --no-preflight`.

### Why not auto-substitute?

Auto-substitution (option 4) requires understanding the semantics of every CUDA-dependent package. For PyTorch, replacing `+cu118` with the macOS wheel is straightforward, but for custom CUDA kernels (`torch.utils.cpp_extension`), there is no MPS equivalent. The substitution logic would be complex and fragile.

---

## Consequences

### Positive

- Users get a clear, early error message instead of cryptic CUDA import failures.
- envguard provides actionable recommendations (use MPS or CPU).
- No false promise of CUDA support.

### Negative

- Projects that work fine on macOS despite listing CUDA dependencies (e.g., projects that gracefully fall back to CPU) will be blocked. Users must use `--no-preflight` to override.
- Some legitimate use cases are blocked: e.g., a project that checks `torch.cuda.is_available()` and falls back to CPU. However, envguard cannot reliably determine that the fallback is correct.

### Configuration

The `reject_cuda_on_macos` setting in `[accelerator]` controls this behavior:

```toml
[accelerator]
reject_cuda_on_macos = true  # default
```

Setting this to `false` will downgrade the CUDA-on-macOS finding from CRITICAL to WARNING, allowing execution to proceed with a warning.

---

## Related

- [docs/limitations.md](../limitations.md) — GPU limitations section
- [docs/troubleshooting.md](../troubleshooting.md) — "CUDA not supported on macOS" section
- ADR-0004: Managed Execution Model — Why preflight is required before execution
