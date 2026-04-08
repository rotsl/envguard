"""Demo that INTENTIONALLY requires CUDA - NOT supported on macOS."""
import torch


def check_cuda():
    """Check if CUDA is available and run a simple computation."""
    if not torch.cuda.is_available():
        print("CUDA is not available. On macOS, use MPS instead.")
        print("Run: python -c \"import torch; print(torch.backends.mps.is_available())\"")
        return False
    print(f"CUDA available: {torch.cuda.get_device_name(0)}")
    device = torch.device("cuda")
    x = torch.randn(3, 3, device=device)
    print(f"Tensor on {device}: {x}")
    return True


def suggest_mps_alternative():
    """Suggest MPS as the macOS alternative to CUDA."""
    print("\n--- macOS Alternative ---")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        print("MPS is available! Replace cuda with mps in your code:")
        print('  device = torch.device("mps")  # instead of "cuda"')
    else:
        print("MPS is not available either. Using CPU is the only option.")
        print('  device = torch.device("cpu")')


if __name__ == "__main__":
    print("=== CUDA Availability Check ===\n")
    available = check_cuda()
    if not available:
        suggest_mps_alternative()
