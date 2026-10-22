VENV_DIR := .venv
PYTHON ?= python
PIP := $(VENV_DIR)/bin/pip
HATCH ?= hatch
ifeq ($(CI),)
RUN := $(HATCH) run python
else
RUN := $(PYTHON)
endif
SPEC_PREVIEW_PNG := docs/assets/webhook_receiver_openapi_spec_preview.png
PLAYWRIGHT_VERSION := 1.54.1
PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.cache/ms-playwright
SWAGGER_PREVIEW_DIR := demo/.preview/swagger-ui
SPEC_PREVIEW_DIR := demo/.preview/spec-preview
SWAGGER_PREVIEW_PORT := 8123
SPEC_PREVIEW_PORT := 8124
EXAMPLES_PREVIEW_PORT := 8130

.PHONY: bootstrap
bootstrap:
	@command -v $(HATCH) >/dev/null || { echo "Install Hatch in an isolated tool environment first"; exit 1; }

.PHONY: ensure-hatch
ensure-hatch:
	@command -v $(HATCH) >/dev/null || { echo "Hatch is required for focused Hatch targets"; exit 1; }

.PHONY: install
install: ensure-hatch
	@$(HATCH) env create
	@if [ -n "$$CI" ]; then \
		echo "CI detected: skipping pre-commit hook installation"; \
	else \
		$(MAKE) precommit-install; \
	fi

.PHONY: install-ci
install-ci:
	@$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
	@$(PYTHON) -m pip install -e ".[dev,docs]"

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
format:
	@$(RUN) -m ruff format src tests tools/verification*.py

.PHONY: format-check
format-check:
	@$(RUN) -m ruff format --check src tests tools/verification*.py

.PHONY: style
style: ensure-hatch
	@$(HATCH) run style

.PHONY: typecheck
typecheck:
	@$(RUN) -m mypy src tests tools/verification*.py

.PHONY: lint
lint: style typecheck

.PHONY: security
security:
	@$(RUN) -m bandit -r src

.PHONY: check
check: format-check typecheck security lint-workflows
	@$(RUN) -m ruff check src tests tools/verification*.py
	@$(RUN) scripts/lint_mermaid.py
	@$(RUN) scripts/check_screenshots.py --strict

.PHONY: lint-workflows
lint-workflows:
	@$(RUN) tools/lint_release_workflows.py
	@$(RUN) tools/lint_workflow_pins.py
	@$(RUN) tools/lint_hatch_matrix.py

.PHONY: check-all
check-all: verify

.PHONY: integration verify report wheel-smoke
integration verify report:
	@$(RUN) -m tools.verification $@

wheel-smoke:
	@$(RUN) -m tools.verification focused wheel-smoke -m tools.verification_wheel

.PHONY: precommit
precommit: ensure-hatch
	@$(HATCH) run precommit

.PHONY: precommit-install
precommit-install: ensure-hatch
	@$(HATCH) run precommit-install

.PHONY: test
test:
	@$(RUN) -m tools.verification test

.PHONY: cov
cov: ensure-hatch
	@$(HATCH) run cov
	@echo "Open htmlcov/index.html in your browser to view the coverage report."
	@echo "coverage.xml generated for Codecov upload."

.PHONY: perf
perf:
	@$(RUN) -m tools.verification focused perf scripts/benchmark_spec_generation.py --check

.PHONY: e2e-local
e2e-local:
	@E2E_BASE_URL=http://localhost:7071 E2E_EXPECTED_VERSION=$${E2E_EXPECTED_VERSION:-$$($(HATCH) version)} $(RUN) -m tools.verification local-e2e

.PHONY: e2e-azure
e2e-azure:
	@$(RUN) -m tools.verification azure-e2e

.PHONY: build
build:
	@$(RUN) -m tools.verification focused build -m build --no-isolation

.PHONY: publish-test
publish-test: ensure-hatch
	@$(HATCH) publish --repo test

.PHONY: version
version: ensure-hatch
	@echo "Current version:"
	@$(HATCH) version

.PHONY: docs
docs:
	@$(RUN) -m tools.verification focused docs -m mkdocs build --strict

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
	@python3 demo/serve_preview.py $(SPEC_PREVIEW_PORT) $(SPEC_PREVIEW_DIR) > /tmp/openapi-spec-preview.log 2>&1 & \
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
	@python3 demo/serve_preview.py $(SWAGGER_PREVIEW_PORT) $(SWAGGER_PREVIEW_DIR) > /tmp/openapi-swagger-preview.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--wait-for-selector ".opblock.is-open" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(SWAGGER_PREVIEW_PORT)/index.html" \
		"docs/assets/webhook_receiver_openapi_swagger_ui_preview.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true

.PHONY: demo-examples
demo-examples: ensure-hatch
	@rm -rf demo/.preview/webhook_receiver demo/.preview/notification_request demo/.preview/partner_import_bridge
	@mkdir -p docs/assets
	@PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) install chromium > /dev/null
	@$(HATCH) run python demo/generate_example_swagger.py \
		--example webhook_receiver \
		--title "Webhook Receiver API" \
		--output-dir demo/.preview/webhook_receiver
	@python3 demo/serve_preview.py $(EXAMPLES_PREVIEW_PORT) demo/.preview/webhook_receiver > /tmp/openapi-webhook.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--full-page \
		--wait-for-selector ".opblock.is-open" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(EXAMPLES_PREVIEW_PORT)/index.html" \
		"docs/assets/webhook_receiver_swagger_ui.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true
	@$(HATCH) run python demo/generate_example_swagger.py \
		--example notification_request \
		--title "Notification API" \
		--output-dir demo/.preview/notification_request
	@python3 demo/serve_preview.py $(EXAMPLES_PREVIEW_PORT) demo/.preview/notification_request > /tmp/openapi-notification.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--full-page \
		--wait-for-selector ".opblock.is-open" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(EXAMPLES_PREVIEW_PORT)/index.html" \
		"docs/assets/notification_request_swagger_ui.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true
	@$(HATCH) run python demo/generate_example_swagger.py \
		--example partner_import_bridge \
		--title "Partner Import API" \
		--output-dir demo/.preview/partner_import_bridge
	@python3 demo/serve_preview.py $(EXAMPLES_PREVIEW_PORT) demo/.preview/partner_import_bridge > /tmp/openapi-partner.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" npx -y playwright@$(PLAYWRIGHT_VERSION) screenshot \
		--device="Desktop Chrome" \
		--full-page \
		--wait-for-selector ".opblock.is-open" \
		--wait-for-timeout 2000 \
		"http://127.0.0.1:$(EXAMPLES_PREVIEW_PORT)/index.html" \
		"docs/assets/partner_import_bridge_swagger_ui.png" > /dev/null; \
	kill $$SERVER_PID 2>/dev/null || true; \
	wait $$SERVER_PID 2>/dev/null || true

.PHONY: doctor
doctor:
	@$(RUN) -m tools.verification doctor

.PHONY: clean
clean:
	@$(RUN) -m tools.verification clean

# Deep clean (maintenance, not part of the canonical contract): artifacts plus the
# project-local virtual environment. `make clean` never touches `.venv`.
.PHONY: clean-all
clean-all: clean
	@find . -type d -name "__pycache__" -not -path "./.git/*" -exec rm -rf {} +
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -not -path "./.git/*" -delete
	@rm -rf .DS_Store $(VENV_DIR)

.PHONY: help
help:
	@echo "Canonical: install install-ci doctor format format-check check test integration verify e2e-azure report clean"
	@echo "check-all: backward-compatible alias for verify (full local gate, requires func + Azurite)"
	@echo "Partial/focused: style lint typecheck security lint-workflows cov perf build wheel-smoke docs docs-serve"
	@echo "Local-emulator only, not Azure certification: e2e-local"
	@echo "Partial/demo (not test prerequisites): demo demo-swagger demo-examples"
	@echo "Environment/maintenance: bootstrap ensure-hatch shell reset hatch-clean clean-all precommit precommit-install publish-test version"
