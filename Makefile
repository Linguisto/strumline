.DEFAULT_GOAL := help
.PHONY: help build build.dev up down init bash lint test test.unit test.integration migrate benchmarks

IMAGE_TAG ?= dev

# Container to exec into for non-host targets.
# Override: make lint DC_EXEC="uv run"
DC_EXEC ?= docker compose run --rm strumline-cli

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@grep -E '^[a-zA-Z_.-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------
build: ## Build the production image (runtime stage, no dev deps)
	STRUMLINE_IMAGE_TAG=$(IMAGE_TAG) STRUMLINE_TARGET=runtime docker compose build

build.dev: ## Build the dev image (includes pytest, ruff, mypy)
	STRUMLINE_IMAGE_TAG=$(IMAGE_TAG) STRUMLINE_TARGET=dev docker compose build

# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------
up: ## Build dev image, start stack, run migrations
	@$(MAKE) init
	@$(MAKE) build.dev
	STRUMLINE_IMAGE_TAG=$(IMAGE_TAG) docker compose up -d --force-recreate
	@$(MAKE) migrate

down: ## Stop and remove containers (keeps volumes)
	docker compose down

init:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from .env.example"; \
	fi
	@perl -i -pe 's/^APP_KEY=$$/sprintf "APP_KEY=%s", unpack("H*", do { open my $$f, "<", "\/dev\/urandom" or die; read $$f, my $$b, 32; $$b })/e' .env \
		&& echo "✓ Generated APP_KEY" || true

bash: ## Open a shell in a disposable CLI container
	docker compose run --rm strumline-cli bash

# ---------------------------------------------------------------------------
# Quality gates — run via DC_EXEC (container by default, override with uv run)
# ---------------------------------------------------------------------------
lint: ## Run ruff, mypy, and import-linter
	$(DC_EXEC) sh -c "ruff check strumline/ tests/ && ruff format --check strumline/ tests/ && mypy strumline/ && lint-imports"

test: ## Run the full test suite
	$(DC_EXEC) pytest

test.unit: ## Run unit tests only (no DB required)
	$(DC_EXEC) pytest -m unit

test.integration: ## Run integration tests only (requires DB)
	$(DC_EXEC) pytest -m integration

migrate: ## Run database migrations to head
	$(DC_EXEC) strumline migrate

# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------
benchmarks: ## Run the receipt-to-enqueue benchmark and write benchmarks/results/
	$(DC_EXEC) python benchmarks/receipt_to_enqueue.py
