"""Demo application for conda-based environments using numpy, pandas, and matplotlib."""
import numpy as np
import pandas as pd


def main():
    print("=== Conda Environment Demo ===")
    print(f"NumPy version:  {np.__version__}")
    print(f"Pandas version: {pd.__version__}")

    # Demonstrate numpy
    data = np.random.randn(100)
    print(f"\nGenerated {len(data)} random values:")
    print(f"  Mean: {data.mean():.4f}")
    print(f"  Std:  {data.std():.4f}")

    # Demonstrate pandas
    df = pd.DataFrame({
        "value": data,
        "squared": data ** 2,
    })
    print(f"\nDataFrame summary:")
    print(df.describe())

    # Demonstrate matplotlib (save to file since we may be headless)
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(data, bins=20, alpha=0.7, color="steelblue", edgecolor="black")
        ax.set_title("Random Data Distribution")
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        plt.tight_layout()
        plt.savefig("conda_demo_histogram.png")
        print("\nHistogram saved to conda_demo_histogram.png")
    except ImportError:
        print("\nmatplotlib not available in this environment.")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
