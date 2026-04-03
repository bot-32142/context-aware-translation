.PHONY: install install-dev test test-py test-ui test-cov test-cov-py test-ui-cov lint format typecheck check clean help eval eval-clean build-ui build-macos-app clean-ui lupdate release

PYTHON := uv run python
PYTEST := uv run pytest
RUFF := uv run ruff
# Invoke tools through Python so they still work if the project directory moves
# and the generated .venv wrapper shebangs become stale.
MYPY := $(PYTHON) -m mypy
LUPDATE := $(PYTHON) -c "import sys; from PySide6.scripts.pyside_tool import lupdate; sys.argv = ['pyside6-lupdate', *sys.argv[1:]]; raise SystemExit(lupdate())"
LRELEASE := $(PYTHON) -c "import sys; from PySide6.scripts.pyside_tool import lrelease; sys.argv = ['pyside6-lrelease', *sys.argv[1:]]; raise SystemExit(lrelease())"

all: check test-cov

install:
	uv sync

install-dev:
	uv sync --group dev

test:
	$(MAKE) test-py
	$(MAKE) test-ui

test-py:
	$(PYTEST) tests/ --ignore=tests/ui/

test-ui:
	$(PYTHON) scripts/run_ui_tests.py

test-cov:
	rm -f .coverage .coverage.*
	$(MAKE) test-cov-py
	$(MAKE) test-ui-cov
	uv run coverage report --show-missing

test-cov-py:
	$(PYTEST) tests/ --ignore=tests/ui/ --cov=context_aware_translation --cov-report=

test-ui-cov:
	$(PYTHON) scripts/run_ui_tests.py \
		--cov=context_aware_translation \
		--cov-report= \
		--cov-append

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

build-macos-app:
	@if [ "$$(uname -s)" != "Darwin" ]; then \
		echo "Error: make build-macos-app is only supported on macOS"; \
		exit 1; \
	fi
	$(PYTHON) scripts/build_ui.py --clean
	@echo ""
	@echo "Local macOS app bundle ready: dist/CAT-UI.app"
	@echo "Open it with: open dist/CAT-UI.app"

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
	echo "  GitHub Actions will build a macOS DMG and Windows zip and create a draft release."

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
	@echo "  make build-macos-app - Build local macOS .app bundle"
	@echo "  make clean-ui     - Clean UI build artifacts"
	@echo "  make release      - Show instructions to create a release"
