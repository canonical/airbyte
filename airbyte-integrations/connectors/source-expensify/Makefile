# Local dev commands for source-expensify.

.PHONY: help install fmt lint test unit-test

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install project dependencies via Poetry.
	poetry install

fmt:  ## Format source code with ruff.
	poetry run ruff format .

lint:  ## Lint source code with ruff.
	poetry run ruff check .

unit-test:  ## Run unit tests with pytest.
	poetry run pytest unit_tests

test: lint unit-test  ## Run lint checks and unit tests.
