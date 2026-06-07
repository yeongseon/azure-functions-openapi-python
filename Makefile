VENV_DIR := .venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip
HATCH := $(VENV_DIR)/bin/hatch
PACKAGE_INIT := $(shell find src -mindepth 2 -maxdepth 2 -name "__init__.py" | head -n1)
SPEC_PREVIEW_PNG := docs/assets/hello_openapi_spec_preview.png
PLAYWRIGHT_VERSION := 1.54.1
PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.cache/ms-playwright
SWAGGER_PREVIEW_DIR := demo/.preview/swagger-ui
SPEC_PREVIEW_DIR := demo/.preview/spec-preview
SWAGGER_PREVIEW_PORT := 8123
SPEC_PREVIEW_PORT := 8124
EXAMPLES_PREVIEW_PORT := 8130

.PHONY: bootstrap
bootstrap:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "Creating virtual environment..."; \
		python3 -m venv $(VENV_DIR); \
	fi
	@echo "Ensuring Hatch is installed in virtual environment..."
	@$(PIP) install --upgrade pip > /dev/null
	@$(PIP) install hatch > /dev/null
	@echo "Hatch installed at $(HATCH)"

.PHONY: ensure-hatch
ensure-hatch: bootstrap

.PHONY: install
install: ensure-hatch
	@$(HATCH) env create
	@if [ -n "$$CI" ]; then \
		echo "CI detected: skipping pre-commit hook installation"; \
	else \
		$(MAKE) precommit-install; \
	fi

.PHONY: shell
shell: ensure-hatch
	@$(HATCH) shell

.PHONY: reset
reset: clean-all install
	@echo "Project reset complete."

.PHONY: hatch-clean
hatch-clean: ensure-hatch
	@$(HATCH) env remove || echo "No hatch environment to remove"

.PHONY: format
format: ensure-hatch
	@$(HATCH) run format

.PHONY: style
style: ensure-hatch
	@$(HATCH) run style

.PHONY: typecheck
typecheck: ensure-hatch
	@$(HATCH) run typecheck

.PHONY: lint
lint: ensure-hatch
	@$(HATCH) run lint

.PHONY: security
security: ensure-hatch
	@$(HATCH) run security

.PHONY: check
check: ensure-hatch
	@$(MAKE) lint
	@$(MAKE) typecheck
	@echo "Lint and type check passed."

.PHONY: check-all
check-all: ensure-hatch
	@$(MAKE) check
	@$(MAKE) test
	@$(MAKE) security
	@echo "All checks passed including tests and security scan."

.PHONY: precommit
precommit: ensure-hatch
	@$(HATCH) run precommit

.PHONY: precommit-install
precommit-install: ensure-hatch
	@$(HATCH) run precommit-install

.PHONY: test
test: ensure-hatch
	@echo "Running tests..."
	@$(HATCH) run test

.PHONY: cov
cov: ensure-hatch
	@$(HATCH) run cov
	@echo "Open htmlcov/index.html in your browser to view the coverage report."
	@echo "coverage.xml generated for Codecov upload."

.PHONY: e2e-local
e2e-local: ensure-hatch
	@echo "Running e2e tests against local Azurite (E2E_BASE_URL=http://localhost:7071)..."
	@E2E_BASE_URL=http://localhost:7071 $(HATCH) run e2e-azure

.PHONY: e2e-azure
e2e-azure: ensure-hatch
	@echo "Running e2e tests against Azure (E2E_BASE_URL must be set)..."
	@$(HATCH) run e2e-azure

.PHONY: build
build: ensure-hatch
	@$(HATCH) build

.PHONY: changelog
changelog: ensure-hatch
	@$(HATCH) run git-cliff $(if $(VERSION),--tag v$(VERSION),) -o CHANGELOG.md
	@echo "Changelog generated."

.PHONY: commit-changelog
commit-changelog:
	@git add CHANGELOG.md
	@git commit -m "docs: update changelog" || echo "No changes to commit"

.PHONY: tag-release
tag-release:
ifndef VERSION
	$(error VERSION is not set. Usage: make tag-release VERSION=1.0.1)
endif
	@git push origin HEAD
	@git tag -a v$(VERSION) -m "Release v$(VERSION)"
	@git push origin v$(VERSION)
	@echo "Tagged release v$(VERSION)"

.PHONY: release
release: ensure-hatch
ifndef VERSION
	$(error VERSION is not set. Usage: make release VERSION=1.0.1)
endif
	@$(HATCH) version $(VERSION)
	@git add "$(PACKAGE_INIT)" && \
	 git commit -m "build: bump version to $(VERSION)"
	@$(MAKE) release-core VERSION=$(VERSION)

.PHONY: release-core
release-core:
ifndef VERSION
	$(error VERSION is not set. Usage: make release-core VERSION=1.0.1)
endif
	@$(MAKE) changelog VERSION=$(VERSION)
	@$(MAKE) commit-changelog
	@$(MAKE) tag-release VERSION=$(VERSION)

.PHONY: release-patch
release-patch: ensure-hatch
	@$(HATCH) version patch
	@VERSION=$$($(HATCH) version | tail -n1); \
	 git add "$(PACKAGE_INIT)" && \
	 git commit -m "build: bump version to $$VERSION" && \
	 $(MAKE) release-core VERSION=$$VERSION

.PHONY: release-minor
release-minor: ensure-hatch
	@$(HATCH) version minor
	@VERSION=$$($(HATCH) version | tail -n1); \
	 git add "$(PACKAGE_INIT)" && \
	 git commit -m "build: bump version to $$VERSION" && \
	 $(MAKE) release-core VERSION=$$VERSION

.PHONY: release-major
release-major: ensure-hatch
	@$(HATCH) version major
	@VERSION=$$($(HATCH) version | tail -n1); \
	 git add "$(PACKAGE_INIT)" && \
	 git commit -m "build: bump version to $$VERSION" && \
	 $(MAKE) release-core VERSION=$$VERSION

.PHONY: publish-test
publish-test: ensure-hatch
	@$(HATCH) publish --repo test

.PHONY: publish-pypi
publish-pypi: ensure-hatch
	@$(HATCH) publish

.PHONY: version
version: ensure-hatch
	@echo "Current version:"
	@$(HATCH) version

.PHONY: docs
docs:
	@if [ -n "$$CI" ]; then \
		echo "CI detected: running MkDocs directly"; \
		python -m pip install --upgrade pip > /dev/null 2>&1 || true; \
		pip install "mkdocs<2.0" "mkdocs-material<10.0" "mkdocstrings[python]<1.0" > /dev/null 2>&1; \
		mkdocs build; \
	else \
		$(MAKE) ensure-hatch > /dev/null; \
		$(HATCH) run mkdocs build; \
	fi

.PHONY: docs-serve
docs-serve: ensure-hatch
	@$(HATCH) run docs

.PHONY: demo
demo: demo-swagger demo-examples

.PHONY: demo-swagger
demo-swagger: ensure-hatch
	@rm -rf $(SWAGGER_PREVIEW_DIR)
	@rm -rf $(SPEC_PREVIEW_DIR)
	@mkdir -p $(SWAGGER_PREVIEW_DIR) $(SPEC_PREVIEW_DIR) docs/assets
	@$(HATCH) run python demo/run_webhook_receiver_example.py --output-dir demo/.preview
	@PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) install chromium > /dev/null
	@python3 -m http.server $(SPEC_PREVIEW_PORT) --directory $(SPEC_PREVIEW_DIR) > /tmp/openapi-spec-preview.log 2>&1 & \
	SPEC_PID=$$!; \
	trap 'kill $$SPEC_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--full-page \
		--wait-for-selector "pre" \
		--wait-for-timeout 1500 \
		"http://127.0.0.1:$(SPEC_PREVIEW_PORT)/index.html" \
		"$(SPEC_PREVIEW_PNG)" > /dev/null; \
	kill $$SPEC_PID 2>/dev/null || true; \
	wait $$SPEC_PID 2>/dev/null || true
	@python3 -m http.server $(SWAGGER_PREVIEW_PORT) --directory $(SWAGGER_PREVIEW_DIR) > /tmp/openapi-swagger-preview.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--wait-for-selector ".opblock.is-open" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(SWAGGER_PREVIEW_PORT)/index.html" \
		"docs/assets/hello_openapi_swagger_ui_preview.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true

.PHONY: demo-examples
demo-examples: ensure-hatch
	@mkdir -p docs/assets
	@PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) install chromium > /dev/null
	@$(HATCH) run python demo/generate_example_swagger.py \
		--example webhook_receiver \
		--title "Webhook Receiver API" \
		--output-dir demo/.preview/webhook_receiver
	@python3 -m http.server $(EXAMPLES_PREVIEW_PORT) --directory demo/.preview/webhook_receiver > /tmp/openapi-webhook.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--full-page \
		--wait-for-selector ".opblock" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(EXAMPLES_PREVIEW_PORT)/index.html" \
		"docs/assets/webhook_receiver_swagger_ui.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true
	@$(HATCH) run python demo/generate_example_swagger.py \
		--example notification_request \
		--title "Notification API" \
		--output-dir demo/.preview/notification_request
	@python3 -m http.server $(EXAMPLES_PREVIEW_PORT) --directory demo/.preview/notification_request > /tmp/openapi-notification.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--full-page \
		--wait-for-selector ".opblock" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(EXAMPLES_PREVIEW_PORT)/index.html" \
		"docs/assets/notification_request_swagger_ui.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true
	@$(HATCH) run python demo/generate_example_swagger.py \
		--example partner_import_bridge \
		--title "Partner Import API" \
		--output-dir demo/.preview/partner_import_bridge
	@python3 -m http.server $(EXAMPLES_PREVIEW_PORT) --directory demo/.preview/partner_import_bridge > /tmp/openapi-partner.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--full-page \
		--wait-for-selector ".opblock" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(EXAMPLES_PREVIEW_PORT)/index.html" \
		"docs/assets/partner_import_bridge_swagger_ui.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true

.PHONY: doctor
doctor:
	@echo "Python version:" && $(PYTHON) --version
	@echo "Installed packages:" && $(HATCH) env run pip list || echo "No hatch environment found"
	@echo "Azure Function Core Tools version:" && func --version || echo "func not found"
	@echo "Pre-commit hook installed:"
	@if [ -f .git/hooks/pre-commit ]; then echo yes; else echo no; fi

.PHONY: clean
clean:
	@rm -rf *.egg-info dist build __pycache__ .pytest_cache

.PHONY: clean-all
clean-all: clean
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
	@rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage coverage.xml htmlcov .DS_Store $(VENV_DIR) site

.PHONY: help
help:
	@echo "Available commands:" && \
	grep -E '^\.PHONY: ' Makefile | cut -d ':' -f2 | xargs -n1 echo "  - make"
