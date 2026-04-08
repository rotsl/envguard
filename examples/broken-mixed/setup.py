"""Setup configuration that intentionally conflicts with the conda environment."""
from setuptools import setup, find_packages

# NOTE: This setup.py CONFLICTS with environment.yml in several ways:
# 1. Different Python version requirement (3.9+ vs conda's 3.10)
# 2. Different numpy/pandas version constraints
# 3. Additional dependencies not in the conda environment
# 4. This creates ambiguity about which source of truth to use

setup(
    name="broken-mixed-demo",
    version="0.1.0",
    description="Intentionally broken mixed pip/conda configuration",
    python_requires=">=3.9",  # Conflicts with environment.yml python=3.10
    install_requires=[
        "numpy>=1.21,<1.26",   # Overlaps with conda but tighter constraint
        "pandas>=1.5,<2.1",    # Overlaps with conda but blocks pandas 2.x
        "requests>=2.25",      # Not in conda environment
        "click>=7.1",          # Conflicts with conda's click>=8.0
        "rich>=12.0",          # Not in conda environment
    ],
    entry_points={
        "console_scripts": [
            "broken-demo=broken_demo:main",
        ],
    },
)
