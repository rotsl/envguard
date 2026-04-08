# Contributing

This document describes how to contribute to envguard, including development setup, code style, testing, commit message conventions, and the PR process.

---

## How to contribute

envguard welcomes contributions of all kinds: bug fixes, new features, documentation improvements, test coverage, and performance optimizations.

### Ways to contribute

1. **Report bugs** — Open an issue on GitHub with a clear description, steps to reproduce, and expected vs. actual behavior.
2. **Fix bugs** — Fork the repo, fix the bug, and submit a PR with a test that reproduces the bug and verifies the fix.
3. **Add features** — Open an issue to discuss the feature before implementing. Include use cases and expected behavior.
4. **Improve documentation** — Fix typos, add examples, clarify confusing sections, or write new documentation.
5. **Add tests** — Increase test coverage for existing code. Tests are always welcome.
6. **Review PRs** — Help review other contributors' pull requests.

---

## Development setup

### Prerequisites

- Python 3.10 or later
- Git
- pip (included with Python)
- Make (optional, for Makefile targets)

### Clone and set up

```bash
# Clone the repository
git clone https://github.com/rohanr/envguard.git
cd envguard

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

### Verify the setup

```bash
# Run the test suite
make test

# Or directly
pytest

# Run the CLI
envguard --help
envguard doctor
```

### Makefile targets

| Target | Command | Description |
|---|---|---|
| `make install` | `pip install -e .` | Install in editable mode |
| `make lint` | `ruff check src/ tests/` | Run linter |
| `make format` | `ruff format src/ tests/` | Auto-format code |
| `make typecheck` | `mypy src/` | Run type checker |
| `make test` | `pytest -v` | Run tests |
| `make test-cov` | `pytest --cov=envguard` | Run tests with coverage |
| `make clean` | `rm -rf .venv/ build/ dist/ *.egg-info` | Clean build artifacts |
| `make check` | `lint + format check + typecheck + test` | Run all checks |
| `make install-hooks` | `envguard install-shell-hooks` | Install shell hooks |
| `make uninstall-hooks` | `envguard uninstall-shell-hooks` | Uninstall shell hooks |
| `make install-agent` | `envguard install-launch-agent` | Install LaunchAgent |
| `make uninstall-agent` | `envguard uninstall-launch-agent` | Uninstall LaunchAgent |

---

## Code style

### Formatting (ruff)

envguard uses [ruff](https://docs.astral.sh/ruff/) for formatting and linting. Configuration is in `pyproject.toml`.

```bash
# Check formatting
ruff format --check src/ tests/

# Auto-format
ruff format src/ tests/

# Run linter
ruff check src/ tests/
```

#### Key rules

- **Line length:** 100 characters (E501 ignored for formatter)
- **Target Python:** 3.10
- **Import sorting:** isort-compatible (via ruff)
- **Naming:** PEP 8 (via N rules)

#### Ruff rule sets

| Set | Rules |
|---|---|
| `E`, `W` | pycodestyle errors and warnings |
| `F` | pyflakes |
| `I` | isort (import sorting) |
| `N` | pep8-naming |
| `UP` | pyupgrade (modernize syntax) |
| `B` | flake8-bugbear (common bugs) |
| `A` | flake8-builtins (shadowing builtins) |
| `SIM` | flake8-simplify (simplify code) |
| `TCH` | flake8-type-checking (type-only imports) |
| `RUF` | ruff-specific rules |

### Type checking (mypy)

envguard uses [mypy](https://mypy.readthedocs.io/) with strict settings. Configuration is in `pyproject.toml`.

```bash
mypy src/
```

#### Type checking requirements

- All functions must have type annotations (`disallow_untyped_defs = true`)
- `Optional` types must be explicit (`strict_optional = true`)
- Return types must be correct (`warn_return_any = true`)
- All imports must be checked (`check_untyped_defs = true`)

### Documentation style

- Use Google-style docstrings for all public classes and methods.
- Include parameter types and return types in docstrings.
- Use `"""` triple double quotes for all docstrings.
- Module-level docstrings should be one sentence describing the module's purpose.

---

## Testing

### Running tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_doctor.py

# Run a specific test
pytest tests/test_doctor.py::test_check_host_system -v
```

### Test markers

Tests can be marked with the following markers (configured in `pyproject.toml`):

| Marker | Description | Usage |
|---|---|---|
| `slow` | Tests that take >5 seconds | `pytest -m "not slow"` |
| `integration` | Integration tests | `pytest -m "not integration"` |
| `macos_only` | Tests that only run on macOS | Automatically skipped on other platforms |

### Writing tests

Tests use [pytest](https://docs.pytest.org/) with the following conventions:

```python
"""Tests for the rules engine."""

from envguard.models import HostFacts, ProjectIntent
from envguard.rules import RulesEngine


class TestCudaOnMacos:
    """Tests for the CUDA-on-macOS rule."""

    def test_cuda_on_macos_raises_critical(self):
        """When CUDA is required on macOS, a CRITICAL finding is produced."""
        facts = HostFacts(
            os_name="Darwin",
            is_macos=True,
            architecture=Architecture.ARM64,
            is_apple_silicon=True,
        )
        intent = ProjectIntent(
            requires_cuda=True,
            dependencies=["torch>=2.0"],
        )
        engine = RulesEngine(facts, intent)
        findings = engine.evaluate()

        cuda_findings = [f for f in findings if f.rule_id == "CUDA_ON_MACOS"]
        assert len(cuda_findings) == 1
        assert cuda_findings[0].severity == FindingSeverity.CRITICAL

    def test_cuda_on_linux_passes(self):
        """When CUDA is required on Linux, no CUDA finding is produced."""
        facts = HostFacts(
            os_name="Linux",
            is_macos=False,
        )
        intent = ProjectIntent(
            requires_cuda=True,
            dependencies=["torch>=2.0"],
        )
        engine = RulesEngine(facts, intent)
        findings = engine.evaluate()

        cuda_findings = [f for f in findings if f.rule_id == "CUDA_ON_MACOS"]
        assert len(cuda_findings) == 0
```

### Test fixtures

Use pytest fixtures for common test data:

```python
import pytest
from envguard.models import HostFacts, Architecture


@pytest.fixture
def macos_host():
    """Return a HostFacts for a standard Apple Silicon Mac."""
    return HostFacts(
        os_name="Darwin",
        os_version="14.2",
        architecture=Architecture.ARM64,
        is_apple_silicon=True,
        is_rosetta=False,
        python_version="3.12.0",
        has_pip=True,
        has_venv=True,
        is_macos=True,
    )


@pytest.fixture
def intel_host():
    """Return a HostFacts for an Intel Mac."""
    return HostFacts(
        os_name="Darwin",
        os_version="13.6",
        architecture=Architecture.X86_64,
        is_apple_silicon=False,
        is_rosetta=False,
        python_version="3.11.0",
        has_pip=True,
        has_venv=True,
        is_macos=True,
    )
```

### Test coverage

```bash
# Run with coverage report
pytest --cov=envguard --cov-report=term-missing

# Run with HTML report
pytest --cov=envguard --cov-report=html
```

Coverage is configured in `pyproject.toml`. The CLI entry point (`cli.py`) is excluded from coverage reporting because it's mostly formatting code.

---

## Commit message conventions

envguard follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

| Type | Description | Example |
|---|---|---|
| `feat` | New feature | `feat(rules): add wheel compatibility check` |
| `fix` | Bug fix | `fix(detect): correct Rosetta detection on macOS 14` |
| `docs` | Documentation | `docs(readme): add quick start guide` |
| `style` | Formatting (no code change) | `style(cli): fix ruff formatting violations` |
| `refactor` | Code refactoring | `refactor(rules): extract finding builder method` |
| `test` | Adding or updating tests | `test(rules): add tests for CUDA-on-macOS rule` |
| `chore` | Maintenance | `chore(ci): update Python version matrix` |
| `perf` | Performance | `perf(detect): cache xcode-select result` |

### Scopes

Common scopes: `cli`, `doctor`, `detect`, `rules`, `repair`, `preflight`, `update`, `security`, `macos`, `launch`, `project`, `resolver`, `models`, `exceptions`, `logging`, `config`, `docs`, `ci`, `tests`.

### Examples

```
feat(preflight): add smoke test import validation

Run import smoke tests for key packages in the resolved environment
after validation passes. Imports are executed in a subprocess to
avoid polluting the current interpreter.

Fixes #42
```

```
fix(rules): handle missing conda-meta directory gracefully

The mixed pip/conda ownership check assumed conda-meta/ always
exists in conda environments. Some conda environments may have
a missing or empty conda-meta/ directory, causing FileNotFoundError.
```

---

## PR process

### Before submitting

1. **Run all checks**: `make check` (runs lint, format check, typecheck, and tests)
2. **Add tests**: All new features and bug fixes should include tests
3. **Update documentation**: If the PR changes behavior, update relevant docs
4. **Check commit messages**: Ensure commits follow conventional commits format

### PR title format

```
<type>(<scope>): <short description>
```

Examples:
- `feat(rules): add wheel compatibility check for Apple Silicon`
- `fix(update): handle network timeout gracefully`
- `docs(troubleshooting): add Rosetta troubleshooting section`

### PR description template

```markdown
## Summary
Brief description of the change.

## Changes
- Change 1
- Change 2
- Change 3

## Testing
- [ ] Unit tests pass
- [ ] Manual testing performed
- [ ] Edge cases considered

## Related issues
Fixes #123
```

### Review process

1. At least one maintainer must review the PR.
2. All CI checks must pass (lint, format, typecheck, tests).
3. Reviewer may request changes, which should be addressed in new commits.
4. Once approved, a maintainer will squash and merge.

### Branch naming

- Feature branches: `feat/<short-description>` (e.g., `feat/wheel-compat-check`)
- Bug fix branches: `fix/<short-description>` (e.g., `fix/rosetta-detection`)
- Documentation: `docs/<short-description>`

---

## Project structure guide

When adding new code, follow the existing module structure:

```
src/envguard/
├── <module_name>.py          # Top-level modules (single responsibility)
├── <subsystem>/              # Related modules grouped in subdirectories
│   ├── __init__.py
│   └── <feature>.py
```

### Adding a new rule

1. Add a method to `RulesEngine` in `src/envguard/rules.py`:
   ```python
   def check_new_rule(self) -> Optional[RuleFinding]:
       """Check for <condition>."""
       if <condition_met>:
           return None
       return self._finding(
           rule_id="NEW_RULE",
           severity=FindingSeverity.WARNING,
           message="Description of the issue",
           remediation="How to fix it",
           auto_repairable=False,
       )
   ```

2. Register the rule in the `evaluate()` method's `rule_methods` list.

3. Add tests in `tests/test_rules.py`.

4. Add the rule to the documentation in `docs/architecture.md`.

### Adding a new CLI command

1. Add a function decorated with `@app.command()` in `src/envguard/cli.py`.
2. Follow existing command patterns (project_dir argument, json_output option, try/except error handling).
3. Add tests using `typer.testing.CliRunner`.
4. Update `docs/command-reference.md`.
5. Update `README.md` command table if needed.

### Adding a new exception

1. Add a class to `src/envguard/exceptions.py` inheriting from `EnvguardError`.
2. Include relevant metadata attributes (similar to existing exceptions).
3. Map the exception to an exit code in `cli.py`'s `handle_error()` if needed.
4. Document in `docs/architecture.md` exception hierarchy.
