VENV := $(CURDIR)/.venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
NPM := npm
CONSOLE_DIR := $(CURDIR)/console
CONSOLE_ASSET_DIR := $(CURDIR)/src/banksia/interfaces/web_console/assets
COMPOSE := docker compose
TEST_COMPOSE := COMPOSE_PROJECT_NAME=banksia-test-db $(COMPOSE)
TREE_IGNORE := .git|.venv|node_modules|dist|build|tmp|.pytest_cache|.mypy_cache|.ruff_cache|.coverage|coverage|htmlcov|__pycache__|*.egg-info|*.pyc

.PHONY: tree clean-local backend-install backend-dev test-backend test-backend-unit test-backend-integration test-backend-integration-local test-backend-db test-backend-e2e-bounded test-backend-e2e-reviewed test-backend-e2e-staged docker-up docker-down docker-logs lint-backend format-backend typecheck-backend pyright-backend check-backend backend-openapi-generate backend-openapi-check console-install console-dev console-format console-format-check console-lint console-typecheck console-openapi-generate console-openapi-check console-test console-test-integration console-e2e console-e2e-real console-build console-package-assets check-console package-build package-verify docs-format docs-format-check docs-contract-check docs-inventory docs-prompt-generate docs-prompt-check prompt-behavior-eval test-docs check-docs install-user-service

tree:
	@tree -a -L 6 --dirsfirst --prune --gitignore -I '$(TREE_IGNORE)'

clean-local:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage htmlcov
	rm -rf build dist src/banksia_ai.egg-info
	rm -rf node_modules console/dist console/node_modules
	rm -rf console/test-results console/playwright-report
	rm -rf $(CONSOLE_ASSET_DIR)

$(PYTHON):
	python3 -m venv .venv

backend-install: $(PYTHON)
	$(PIP) install --upgrade pip
	$(PIP) install --upgrade -e ".[dev]"

backend-dev: $(PYTHON)
	PYTHONPATH=$(CURDIR)/src $(UVICORN) banksia.main:app --reload --reload-dir $(CURDIR)/src

docker-up:
	$(COMPOSE) up -d --wait postgres

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f --tail=200

test-backend: test-backend-unit

test-backend-unit: $(PYTHON)
	PYTHONPATH=$(CURDIR)/src $(PYTEST) tests/unit

test-backend-integration: $(PYTHON)
	PYTEST_BIN=$(PYTEST) PYTHONPATH=$(CURDIR)/src sh scripts/testing/run_backend_pytest_groups.sh integration

test-backend-integration-local: test-backend-integration

test-backend-db:
	@set -eu; \
	cleanup() { $(TEST_COMPOSE) down --volumes --remove-orphans; }; \
	trap cleanup EXIT INT TERM; \
	$(TEST_COMPOSE) up -d --wait postgres-test; \
	$(TEST_COMPOSE) exec -T postgres-test sh -lc "psql -U banksia -d postgres -c \"DROP DATABASE IF EXISTS banksia_test WITH (FORCE)\" && psql -U banksia -d postgres -c \"CREATE DATABASE banksia_test\""; \
	$(TEST_COMPOSE) build backend-test; \
	$(TEST_COMPOSE) run --rm -e PYTEST_ADDOPTS backend-test

test-backend-e2e-bounded: $(PYTHON)
	PYTEST_BIN=$(PYTEST) PYTHONPATH=$(CURDIR)/src sh scripts/testing/run_backend_pytest_groups.sh e2e-bounded

test-backend-e2e-reviewed: $(PYTHON)
	PYTEST_BIN=$(PYTEST) PYTHONPATH=$(CURDIR)/src sh scripts/testing/run_backend_pytest_groups.sh e2e-reviewed

test-backend-e2e-staged: $(PYTHON)
	PYTEST_BIN=$(PYTEST) PYTHONPATH=$(CURDIR)/src sh scripts/testing/run_backend_pytest_groups.sh e2e-staged

lint-backend: $(PYTHON)
	$(RUFF) check src tests

format-backend: $(PYTHON)
	$(RUFF) format src tests

typecheck-backend: $(PYTHON)
	MYPYPATH=src:. $(MYPY) src tests

pyright-backend:
	npx --yes pyright

check-backend: $(PYTHON)
	$(MAKE) lint-backend
	$(MAKE) typecheck-backend
	$(MAKE) pyright-backend

backend-openapi-generate: $(PYTHON)
	@product_file=$$(mktemp); \
	support_file=$$(mktemp); \
	cleanup() { rm -f "$$product_file" "$$support_file"; }; \
	trap cleanup EXIT INT TERM; \
	PYTHONPATH=$(CURDIR)/src $(PYTHON) scripts/backend/export_openapi.py --surface product > "$$product_file"; \
	PYTHONPATH=$(CURDIR)/src $(PYTHON) scripts/backend/export_openapi.py --surface support > "$$support_file"; \
	mkdir -p openapi; \
	install -m 0644 "$$product_file" openapi/product.json; \
	install -m 0644 "$$support_file" openapi/support.json

backend-openapi-check: $(PYTHON)
	@product_file=$$(mktemp); \
	support_file=$$(mktemp); \
	cleanup() { rm -f "$$product_file" "$$support_file"; }; \
	trap cleanup EXIT INT TERM; \
	PYTHONPATH=$(CURDIR)/src $(PYTHON) scripts/backend/export_openapi.py --surface product > "$$product_file"; \
	PYTHONPATH=$(CURDIR)/src $(PYTHON) scripts/backend/export_openapi.py --surface support > "$$support_file"; \
	diff -u openapi/product.json "$$product_file"; \
	diff -u openapi/support.json "$$support_file"

console-install:
	$(NPM) --prefix $(CONSOLE_DIR) ci

console-dev:
	$(NPM) --prefix $(CONSOLE_DIR) run dev

console-format:
	$(NPM) --prefix $(CONSOLE_DIR) run format

console-format-check:
	$(NPM) --prefix $(CONSOLE_DIR) run format:check

console-lint:
	$(NPM) --prefix $(CONSOLE_DIR) run lint

console-typecheck:
	$(NPM) --prefix $(CONSOLE_DIR) run typecheck

console-openapi-generate:
	$(NPM) --prefix $(CONSOLE_DIR) run openapi:generate

console-openapi-check:
	@types_file=$$(mktemp); \
	cleanup() { rm -f "$$types_file"; }; \
	trap cleanup EXIT INT TERM; \
	$(NPM) --prefix $(CONSOLE_DIR) exec -- openapi-typescript $(CURDIR)/openapi/product.json -o "$$types_file" >/dev/null; \
	diff -u $(CONSOLE_DIR)/src/api/generated/openapi.ts "$$types_file"

console-test:
	$(NPM) --prefix $(CONSOLE_DIR) run test

console-test-integration:
	$(NPM) --prefix $(CONSOLE_DIR) run test:integration

console-e2e:
	$(NPM) --prefix $(CONSOLE_DIR) run test:e2e

console-e2e-real: console-package-assets
	$(NPM) --prefix $(CONSOLE_DIR) run test:e2e:real

console-build:
	$(NPM) --prefix $(CONSOLE_DIR) run build

console-package-assets: console-build
	rm -rf $(CONSOLE_ASSET_DIR)
	mkdir -p $(CONSOLE_ASSET_DIR)
	cp -R $(CONSOLE_DIR)/dist/. $(CONSOLE_ASSET_DIR)/

check-console:
	$(MAKE) console-format-check
	$(MAKE) console-lint
	$(MAKE) console-typecheck
	$(MAKE) console-openapi-check
	$(MAKE) console-test
	$(MAKE) console-test-integration
	$(MAKE) console-build

package-build: $(PYTHON) console-package-assets
	rm -rf $(CURDIR)/dist
	$(PYTHON) -m build
	PYTHONPATH=$(CURDIR)/src $(PYTHON) scripts/testing/verify_installed_distribution.py \
		--dist-dir $(CURDIR)/dist \
		--artifacts-only

package-verify: package-build
	@set -eu; \
	workspace=$$(mktemp -d); \
	cleanup() { rm -rf "$$workspace"; }; \
	trap cleanup EXIT INT TERM; \
	PYTHONPATH=$(CURDIR)/src $(PYTHON) scripts/testing/verify_installed_distribution.py \
		--dist-dir $(CURDIR)/dist \
		--workspace "$$workspace"

docs-format: $(PYTHON)
	$(PYTHON) -m scripts.docs.format_markdown --write

docs-format-check: $(PYTHON)
	$(PYTHON) -m scripts.docs.format_markdown --check

docs-contract-check: $(PYTHON)
	$(PYTHON) -m scripts.docs.docs_contract.cli validate

docs-inventory: $(PYTHON)
	$(PYTHON) -m scripts.docs.docs_contract.cli inventory

docs-prompt-generate: $(PYTHON)
	PYTHONPATH=$(CURDIR)/src $(PYTHON) -m scripts.docs.prompt_catalog.cli generate

docs-prompt-check: $(PYTHON)
	PYTHONPATH=$(CURDIR)/src $(PYTHON) -m scripts.docs.prompt_catalog.cli validate

prompt-behavior-eval: $(PYTHON)
	PYTHONPATH=$(CURDIR)/src $(PYTHON) -m scripts.docs.prompt_catalog.evaluation $(PROMPT_EVAL_ARGS)

test-docs: $(PYTHON)
	@mkdir -p $(CURDIR)/tmp
	TMPDIR=$(CURDIR)/tmp PYTHONPATH=$(CURDIR)/src $(PYTEST) \
		tests/unit/test_docs_contract.py \
		tests/unit/test_workflow_fixture_contract.py \
		tests/unit/test_prompt_catalog_tooling.py

check-docs: $(PYTHON)
	$(MAKE) docs-format-check
	$(MAKE) docs-contract-check
	$(MAKE) docs-prompt-check
	$(MAKE) test-docs
	git diff --check

install-user-service:
	bash scripts/install-systemd-user.sh
