"""Demo for Apple MPS (Metal Performance Shaders) usage."""
import torch


def check_mps():
    """Check if MPS is available and run a simple computation."""
    if hasattr(torch.backends, "mps"):
        if torch.backends.mps.is_available():
            print("MPS is available!")
            device = torch.device("mps")
            x = torch.randn(3, 3, device=device)
            print(f"Tensor on {device}: {x}")
            return True
        else:
            print("MPS not available on this machine.")
            print("Possible reasons:")
            print("  - Not running on Apple Silicon (M1/M2/M3/M4)")
            print("  - PyTorch version does not support MPS")
            return False
    else:
        print("MPS not supported in this PyTorch version.")
        return False


def check_system_info():
    """Print system information relevant to MPS."""
    import platform
    import sys

    print(f"Python:     {sys.version}")
    print(f"Platform:   {platform.platform()}")
    print(f"PyTorch:    {torch.__version__}")
    print(f"MPS built:  {torch.backends.mps.is_built()}")
    print()


if __name__ == "__main__":
    print("=== MPS Availability Check ===\n")
    check_system_info()
    available = check_mps()
    print()
    if available:
        print("[OK] MPS acceleration is ready to use.")
    else:
        print("[!] MPS is not available. Falling back to CPU.")
