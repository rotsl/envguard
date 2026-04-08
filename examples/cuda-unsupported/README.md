# cuda-unsupported

> **Intentionally unsupported** example demonstrating CUDA usage on macOS.

## Purpose

This project intentionally requires NVIDIA CUDA, which is **NOT supported on
macOS**. It exists to test that envguard correctly detects and reports this
unsupported configuration, and provides actionable remediation guidance.

## Why this matters

Apple Silicon Macs (M1/M2/M3/M4) and Intel Macs do not support NVIDIA CUDA.
Projects that depend on CUDA will fail to run GPU-accelerated code on macOS.
PyTorch on macOS supports **MPS (Metal Performance Shaders)** as an alternative
GPU backend.

## Expected envguard behavior

envguard should:

1. **Detect CUDA dependency** from `requirements.txt` and `environment.yml`
2. **Flag as unsupported** with `FindingSeverity.ERROR`
3. **Suggest MPS alternative** for Apple Silicon Macs
4. **Provide remediation** commands to switch to MPS-compatible PyTorch

## Expected envguard output

```
$ envguard detect
✗  CUDA dependency detected - NOT supported on macOS (darwin/arm64)
→  Remediation: Use MPS backend instead
   pip install torch torchvision torchaudio
   In code: torch.device("mps") instead of torch.device("cuda")

$ envguard preflight
✗  FAIL: Accelerator compatibility - CUDA not available on this platform
```
