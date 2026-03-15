# =============================================================================
# Makefile — hasos_more_modules local development helpers
#
# Usage:
#   make help               Show this help
#   make test               Run all tests (Python + shell)
#   make test-python        Run Python tests only
#   make test-shell         Run shell tests only (probe_gpl_symbols)
#   make validate           Validate JSON configs
#   make readme             Regenerate README module table
#   make check-releases     Detect missing HAOS versions (needs GITHUB_TOKEN)
#   make matrix             Generate CI matrix JSON
#   make lint               Run shellcheck + Python static checks
#   make clean              Remove generated temp files
# =============================================================================

.DEFAULT_GOAL := help
.PHONY: help test test-python test-shell validate readme readme-dry \
        check-releases matrix lint probe-test test-patch-config clean

PYTHON   := python3
SCRIPTS  := scripts/
TESTS    := tests/

GITHUB_TOKEN ?=
HAOS_REPO  ?= home-assistant/operating-system
THIS_REPO  ?= dianlight/hasos_more_modules

# ---------------------------------------------------------------------------
help:
	@echo ""
	@echo "hasos_more_modules — local development targets"
	@echo ""
	@echo "  make test              Run all tests"
	@echo "  make test-python       Python tests only (pytest)"
	@echo "  make test-shell        Shell tests only"
	@echo "  make validate          Validate config/modules.json + renovate.json"
	@echo "  make readme            Regenerate README module table"
	@echo "  make readme-dry        Preview README changes (no write)"
	@echo "  make check-releases    Detect missing HAOS versions"
	@echo "  make matrix            Generate CI matrix"
	@echo "  make lint              shellcheck + Python syntax"
	@echo "  make clean             Remove temp files"
	@echo ""

# ---------------------------------------------------------------------------
test: test-python test-shell validate
	@echo ""
	@echo "All tests passed."

test-python:
	@echo "=== Python tests ==="
	@if command -v pytest >/dev/null 2>&1; then \
		pytest $(TESTS) -v --tb=short; \
	else \
		$(PYTHON) -m pytest $(TESTS) -v --tb=short 2>/dev/null || \
		$(PYTHON) -m unittest discover -s $(TESTS) -p "test_*.py" -v; \
	fi

test-shell:
	@echo "=== Shell tests ==="
	bash $(TESTS)test_probe_gpl_symbols.sh

# ---------------------------------------------------------------------------
validate:
	@echo "=== JSON validation ==="
	@$(PYTHON) -c "\
import json, sys; \
data = json.load(open('config/modules.json')); \
assert 'modules' in data and 'boards' in data and 'zfs_build' in data, 'Missing top-level keys'; \
assert data['zfs_build']['modules_order'][-1] == 'zfs', 'zfs must be last in modules_order'; \
board_names = set(data['boards']); \
errors = []; \
[errors.extend([f'{m[\"name\"]}: unknown board {b!r}' \
  for b in m.get('exclude_boards',{}).get('hard',[]) + m.get('exclude_boards',{}).get('soft_neon',[]) \
  if b not in board_names]) for m in data['modules']]; \
[sys.exit(1) or print(e) for e in errors]; \
print('  config/modules.json OK'); \
"
	@$(PYTHON) -c "import json; json.load(open('renovate.json')); print('  renovate.json OK')"

# ---------------------------------------------------------------------------
readme:
	@echo "=== Regenerating README module table ==="
	$(PYTHON) $(SCRIPTS)update_readme_modules.py --readme README.md --modules config/modules.json
	@git diff --stat README.md 2>/dev/null || true

readme-dry:
	$(PYTHON) $(SCRIPTS)update_readme_modules.py --readme README.md --modules config/modules.json --dry-run

# ---------------------------------------------------------------------------
check-releases:
	@echo "=== Checking for missing HAOS releases ==="
	GITHUB_TOKEN="$(GITHUB_TOKEN)" \
	$(PYTHON) $(SCRIPTS)check_releases.py \
		--haos-repo "$(HAOS_REPO)" \
		--this-repo "$(THIS_REPO)" \
		--output missing_versions.json

matrix: missing_versions.json
	$(PYTHON) $(SCRIPTS)build_matrix.py \
		--missing missing_versions.json \
		--modules config/modules.json \
		--output  matrix.json

missing_versions.json:
	@echo "Run 'make check-releases' first"; exit 1

# ---------------------------------------------------------------------------
lint:
	@echo "=== shellcheck ==="
	@if command -v shellcheck >/dev/null 2>&1; then \
		find scripts/ tests/ -name '*.sh' -print0 | \
		xargs -0 shellcheck --severity=warning --exclude=SC2086 && \
		echo "  shellcheck OK"; \
	else \
		echo "  shellcheck not installed — skipping"; \
	fi
	@echo "=== Python syntax ==="
	@find scripts/ tests/ -name '*.py' -exec $(PYTHON) -m py_compile {} + && \
		echo "  Python syntax OK"

probe-test:
	bash $(TESTS)test_probe_gpl_symbols.sh

test-patch-config:
	@KCONFIG=/tmp/haos_patch_test.config; \
	cp /boot/config-$$(uname -r) $$KCONFIG 2>/dev/null || \
		{ echo "Kernel config not found, creating minimal"; \
		  printf 'CONFIG_MODULES=y\n# CONFIG_XFS_FS is not set\n# CONFIG_NFSD is not set\n# CONFIG_NFS_FS is not set\n' > $$KCONFIG; }; \
	KERNEL_CONFIG=$$KCONFIG TARGET_ARCH=x86_64 TARGET_BOARD=x86_64 REPO_ROOT=$$(pwd) \
		bash scripts/patch_config.sh $$KCONFIG x86_64 x86_64 | $(PYTHON) -m json.tool

# ---------------------------------------------------------------------------
clean:
	@rm -f missing_versions.json matrix.json /tmp/haos_patch_test.config
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name '*.pyc' -delete 2>/dev/null || true
	@echo "Cleaned."
