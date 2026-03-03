.PHONY: install install-dev test lint format typecheck check clean help eval eval-clean build-ui clean-ui lupdate release

PYTHON := uv run python
PYTEST := uv run pytest
RUFF := uv run ruff
MYPY := uv run mypy
LUPDATE := uv run pyside6-lupdate
LRELEASE := uv run pyside6-lrelease

all: check test-cov

install:
	uv sync

install-dev:
	uv sync --group dev

test:
	$(PYTEST) tests/

test-cov:
	$(PYTEST) tests/ --cov=context_aware_translation --cov-report=term-missing

lint:
	$(RUFF) check context_aware_translation/ tests/

lint-fix:
	$(RUFF) check --fix context_aware_translation/ tests/

format:
	$(RUFF) format context_aware_translation/ tests/

format-check:
	$(RUFF) format --check context_aware_translation/ tests/

typecheck:
	$(MYPY) context_aware_translation/

check: lint-fix format typecheck lupdate

check-fix: lint-fix format

TS_FILE := context_aware_translation/ui/translations/zh_CN.ts
QM_FILE := context_aware_translation/ui/translations/zh_CN.qm

lupdate:
	$(LUPDATE) -extensions py context_aware_translation/ui/ -ts $(TS_FILE)
	@if grep -c 'type="unfinished"' $(TS_FILE) > /dev/null 2>&1; then \
		echo "ERROR: Found untranslated strings in $(TS_FILE):"; \
		grep -B2 'type="unfinished"' $(TS_FILE); \
		exit 1; \
	fi
	$(LRELEASE) $(TS_FILE) -qm $(QM_FILE)

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Build UI targets
build-ui:
	$(PYTHON) scripts/build_ui.py --clean

clean-ui:
	$(PYTHON) scripts/build_ui.py --no-build --clean

# Evaluation targets
EVAL_DIR := evaluation
EVAL_OUTPUT := evaluation/output
EVAL_CONFIG := .config.yaml
EVAL_LANGUAGE := 简体中文

eval-clean:
	rm -rf $(EVAL_OUTPUT)

eval: eval-clean
	@echo "Running evaluation on $(EVAL_DIR)..."
	$(PYTHON) scripts/run_eval.py \
		--config $(EVAL_CONFIG) \
		--language "$(EVAL_LANGUAGE)" \
		--eval-dir $(EVAL_DIR) \
		--output-dir $(EVAL_OUTPUT)

release:
	@VERSION=$$($(PYTHON) -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"); \
	echo "Creating release v$$VERSION..."; \
	echo "  1. Ensure all changes are committed"; \
	echo "  2. Run: git tag v$$VERSION"; \
	echo "  3. Run: git push origin v$$VERSION"; \
	echo "  GitHub Actions will build macOS and Windows installers and create a draft release."

help:
	@echo "Available commands:"
	@echo "  make install      - Install project dependencies"
	@echo "  make install-dev  - Install with dev dependencies"
	@echo "  make test         - Run tests"
	@echo "  make test-cov     - Run tests with coverage"
	@echo "  make lint         - Run ruff linter"
	@echo "  make lint-fix     - Run ruff linter with auto-fix"
	@echo "  make format       - Format code with ruff"
	@echo "  make format-check - Check code formatting"
	@echo "  make typecheck    - Run mypy type checking"
	@echo "  make check        - Run all checks (lint, format, typecheck, lupdate)"
	@echo "  make check-fix    - Run lint-fix and format"
	@echo "  make lupdate      - Update translation files (.ts and .qm)"
	@echo "  make clean        - Remove cache directories"
	@echo "  make eval         - Run evaluation on sample documents"
	@echo "  make eval-clean   - Clean evaluation output folder"
	@echo "  make build-ui     - Build standalone UI application"
	@echo "  make clean-ui     - Clean UI build artifacts"
	@echo "  make release      - Show instructions to create a release"
