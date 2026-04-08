# broken-mixed

> **Intentionally broken example** showing mixed pip/conda configuration issues.

## Purpose

This example demonstrates common problems that arise when a project mixes
conda environment definitions with pip-based configuration (e.g., `setup.py`)
in ways that create conflicting or ambiguous package management scenarios.

## What's broken here

1. **Conflicting package managers**: The `environment.yml` specifies conda
   dependencies while `setup.py` declares its own `install_requires`, leading
   to potential version conflicts and unclear installation order.

2. **Ambiguous Python version**: The conda environment pins Python 3.10 while
   `setup.py` declares `python_requires >= "3.9"`, creating ambiguity about
   the intended runtime.

3. **Overlapping dependencies**: Both `environment.yml` and `setup.py` list
   overlapping packages with different version constraints.

## How envguard handles this

envguard detects these issues through:

- **Project discovery**: Identifies both `environment.yml` and `setup.py`
  as active configuration files.
- **Intent analysis**: Flags the mixed package manager scenario as a
  finding with `FindingSeverity.WARNING`.
- **Resolution**: Recommends consolidating to a single package management
  approach (either conda-only or pip-only).

## Expected envguard output

```
$ envguard detect
⚠  Mixed configuration detected: environment.yml + setup.py
⚠  Conflicting package managers: conda + pip
⚠  Overlapping dependencies: numpy, pandas
→  Recommendation: Consolidate to a single package manager
```
