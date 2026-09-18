.DEFAULT_GOAL := help
.PHONY: help build build.dev up down install update init init.dev bash lint test migrate

IMAGE_TAG ?= dev

# Container to exec into for non-host targets.
# Override: make lint DC_EXEC="docker compose exec api"
DC_EXEC ?= docker compose run --rm telemetria-cli

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@grep -E '^[a-zA-Z_.-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Host operations (build / start / stop)
# ---------------------------------------------------------------------------
build: ## Build the production image (runtime stage, no dev deps)
	TELEMETRIA_IMAGE_TAG=$(IMAGE_TAG) TELEMETRIA_TARGET=runtime docker compose build

build.dev: ## Build the dev image (includes pytest, ruff, mypy)
	TELEMETRIA_IMAGE_TAG=$(IMAGE_TAG) TELEMETRIA_TARGET=dev docker compose build

up: ## Start all services (detached)
	TELEMETRIA_IMAGE_TAG=$(IMAGE_TAG) docker compose up -d --wait --force-recreate

down: ## Stop and remove containers (keeps volumes)
	docker compose down

bash: ## Open a shell in a disposable CLI container
	docker compose run --rm telemetria-cli bash

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------
init: ## Set up base environment (compose.yaml + .env from examples)
	@if [ ! -f compose.yaml ]; then \
		cp docker/compose.example.yaml compose.yaml; \
		echo "✓ Created compose.yaml"; \
	else \
		echo "✓ compose.yaml already exists (not overwritten)"; \
	fi
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from .env.example"; \
	else \
		echo "✓ .env already exists (not overwritten)"; \
	fi
	@echo ""
	@echo "  Next: make build && make install"

init.dev: ## Set up dev environment (init + hot-reload compose override)
	@$(MAKE) init
	@if [ ! -f docker-compose.override.yaml ]; then \
		cp docker/compose.dev.yaml docker-compose.override.yaml; \
		echo "✓ Created docker-compose.override.yaml (hot reload + dev image)"; \
	else \
		echo "✓ docker-compose.override.yaml already exists (not overwritten)"; \
	fi
	@echo ""
	@echo "  Next: make build.dev && make install"

install: ## Start the stack and run migrations
	@$(MAKE) init.dev
	@$(MAKE) build.dev
	@$(MAKE) up
	@$(MAKE) migrate

update: ## Rebuild image, restart services, run migrations
	@$(MAKE) down
	@$(MAKE) build.dev
	@$(MAKE) up
	@$(MAKE) migrate

# ---------------------------------------------------------------------------
# Container operations — run via DC_EXEC
# ---------------------------------------------------------------------------
lint: ## Run ruff, mypy, and import-linter
	$(DC_EXEC) sh -c "ruff check telemetria/ tests/ && ruff format --check telemetria/ tests/ && mypy telemetria/ && lint-imports"

test: ## Run the test suite
	$(DC_EXEC) pytest

migrate: ## Run database migrations to head
	$(DC_EXEC) telemetria migrate
