.DEFAULT_GOAL := help

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

poetry-lock-check: ## Validate the exact Poetry toolchain and committed lock
	python3 scripts/check_poetry_toolchain.py --active
	poetry check --lock

lint: ## Ruff lint
	poetry run ruff check .

format: ## Format source and tests
	poetry run ruff format .

format-check: ## Verify formatting
	poetry run ruff format --check .

type-check: ## Strict mypy
	poetry run mypy

test: ## Unit and architecture tests
	poetry run pytest -q tests/unit tests/architecture

test-integration: ## PostgreSQL migration, RLS, and receipt-ledger canaries
	poetry run pytest -q tests/integration

migrate: ## Apply Cloud migrations with the separately installed admin URL
	poetry run alembic upgrade head

readiness-report: ## Report current Cloud V1 composition blockers
	poetry run python -m dotmac_cloud --json

production-readiness: ## Fail unless every required owner is released and composed
	poetry run python -m dotmac_cloud --require-ready

check: poetry-lock-check lint format-check type-check test readiness-report ## Canonical CI gate

.PHONY: help poetry-lock-check lint format format-check type-check test test-integration migrate readiness-report production-readiness check
