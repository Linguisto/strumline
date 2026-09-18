.DEFAULT_GOAL := help
.PHONY: help build build.dev up down init bash lint test test.unit test.integration migrate

IMAGE_TAG ?= dev

# Container to exec into for non-host targets.
# Override: make lint DC_EXEC="uv run"
DC_EXEC ?= docker compose run --rm telemetria-cli

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
	TELEMETRIA_IMAGE_TAG=$(IMAGE_TAG) TELEMETRIA_TARGET=runtime docker compose build

build.dev: ## Build the dev image (includes pytest, ruff, mypy)
	TELEMETRIA_IMAGE_TAG=$(IMAGE_TAG) TELEMETRIA_TARGET=dev docker compose build

# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------
up: ## Build dev image, start stack, run migrations
	@$(MAKE) init
	@$(MAKE) build.dev
	TELEMETRIA_IMAGE_TAG=$(IMAGE_TAG) docker compose up -d --force-recreate
	@$(MAKE) migrate

down: ## Stop and remove containers (keeps volumes)
	docker compose down

init:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from .env.example"; \
	fi

bash: ## Open a shell in a disposable CLI container
	docker compose run --rm telemetria-cli bash

# ---------------------------------------------------------------------------
# Quality gates — run via DC_EXEC (container by default, override with uv run)
# ---------------------------------------------------------------------------
lint: ## Run ruff, mypy, and import-linter
	$(DC_EXEC) sh -c "ruff check telemetria/ tests/ && ruff format --check telemetria/ tests/ && mypy telemetria/ && lint-imports"

test: ## Run the full test suite
	$(DC_EXEC) pytest

test.unit: ## Run unit tests only (no DB required)
	$(DC_EXEC) pytest -m unit

test.integration: ## Run integration tests only (requires DB)
	$(DC_EXEC) pytest -m integration

migrate: ## Run database migrations to head
	$(DC_EXEC) telemetria migrate
