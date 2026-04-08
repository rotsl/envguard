.PHONY: install install-dev install-guardenv lint format typecheck test test-cov test-fast \
        test-integration test-unit clean check check-all \
        install-hooks uninstall-hooks install-agent uninstall-agent \
        bootstrap preflight doctor freeze status update rollback \
        docs-check help

# Default target
.DEFAULT_GOAL := help

# ──────────────────────────────────────────────────────────────────────
# Installation
# ──────────────────────────────────────────────────────────────────────

install:
	pip install -e ".[dev]"

install-dev:
	pip install -e ".[dev]"

## Create the guardenv dev/test venv (recommended workflow)
install-guardenv:
	python3 -m venv guardenv
	guardenv/bin/pip install -e ".[dev]"
	@echo ""
	@echo "guardenv ready. Invoke directly: guardenv/bin/envguard --help"
	@echo "Or activate:  source guardenv/bin/activate"

# ──────────────────────────────────────────────────────────────────────
# Code quality
# ──────────────────────────────────────────────────────────────────────

lint:
	ruff check src/ tests/

lint-fix:
	ruff check --fix src/ tests/

format:
	ruff format src/ tests/

format-check:
	ruff format --check src/ tests/

typecheck:
	mypy src/

# ──────────────────────────────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────────────────────────────

test:
	pytest tests/ -v

test-fast:
	pytest tests/ -v -m "not slow and not integration"

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-cov:
	pytest tests/ -v --cov=envguard --cov-report=term-missing

test-cov-xml:
	pytest tests/ -v --cov=envguard --cov-report=term-missing --cov-report=xml:coverage.xml

## Run all quality gates (lint + typecheck + test)
check: lint typecheck test

## Run all quality gates including coverage
check-all: lint format-check typecheck test-cov

# ──────────────────────────────────────────────────────────────────────
# envguard CLI shortcuts (uses guardenv if present, otherwise PATH)
# ──────────────────────────────────────────────────────────────────────

ENVGUARD := $(shell test -f guardenv/bin/envguard && echo guardenv/bin/envguard || echo envguard)

preflight:
	$(ENVGUARD) preflight

doctor:
	$(ENVGUARD) doctor

status:
	$(ENVGUARD) status

freeze:
	$(ENVGUARD) freeze

update:
	$(ENVGUARD) update --dry-run

rollback:
	$(ENVGUARD) rollback

# ──────────────────────────────────────────────────────────────────────
# Shell hooks and LaunchAgent
# ──────────────────────────────────────────────────────────────────────

install-hooks:
	$(ENVGUARD) install-shell-hooks

uninstall-hooks:
	$(ENVGUARD) uninstall-shell-hooks

install-agent:
	$(ENVGUARD) install-launch-agent

uninstall-agent:
	$(ENVGUARD) uninstall-launch-agent

# ──────────────────────────────────────────────────────────────────────
# Bootstrap
# ──────────────────────────────────────────────────────────────────────

## Run the full bootstrap script (interactive)
bootstrap:
	bash scripts/bootstrap.sh

## Run bootstrap non-interactively (accept all prompts)
bootstrap-yes:
	bash scripts/bootstrap.sh --yes

# ──────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────

clean:
	rm -rf dist build *.egg-info .pytest_cache .mypy_cache .ruff_cache coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

clean-all: clean
	rm -rf guardenv/

# ──────────────────────────────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────────────────────────────

help:
	@echo "envguard – macOS-first Python environment orchestration framework"
	@echo "Repository: https://github.com/rotsl/envguard"
	@echo ""
	@echo "Installation:"
	@echo "  install-guardenv    Create guardenv/ dev venv (recommended)"
	@echo "  install             pip install -e '.[dev]' into current env"
	@echo ""
	@echo "Code quality:"
	@echo "  lint                ruff check src/ tests/"
	@echo "  lint-fix            ruff check --fix src/ tests/"
	@echo "  format              ruff format src/ tests/"
	@echo "  format-check        ruff format --check (CI mode)"
	@echo "  typecheck           mypy src/"
	@echo ""
	@echo "Testing:"
	@echo "  test                Full test suite (264 tests)"
	@echo "  test-fast           Skip slow/integration tests"
	@echo "  test-unit           Unit tests only"
	@echo "  test-integration    Integration tests only"
	@echo "  test-cov            Test suite with coverage report"
	@echo ""
	@echo "Quality gates:"
	@echo "  check               lint + typecheck + test"
	@echo "  check-all           lint + format-check + typecheck + test-cov"
	@echo ""
	@echo "envguard CLI:"
	@echo "  preflight           Run preflight checks"
	@echo "  doctor              Run all 10 diagnostic checks"
	@echo "  status              Show environment status"
	@echo "  freeze              Capture environment snapshot"
	@echo "  update              Check for updates (dry run)"
	@echo "  rollback            Rollback to previous snapshot"
	@echo ""
	@echo "Shell & LaunchAgent (macOS):"
	@echo "  install-hooks       Install zsh/bash shell integration"
	@echo "  uninstall-hooks     Remove shell integration"
	@echo "  install-agent       Install macOS LaunchAgent for auto-updates"
	@echo "  uninstall-agent     Remove macOS LaunchAgent"
	@echo ""
	@echo "Bootstrap:"
	@echo "  bootstrap           Run interactive bootstrap script"
	@echo "  bootstrap-yes       Run bootstrap non-interactively"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean               Remove build artifacts and caches"
	@echo "  clean-all           clean + remove guardenv/"
