# Local dev commands for source-expensify.

POETRY := poetry
SCRIPT := $(POETRY) run source-expensify
CONFIG := --config secrets/config.json
LICENSE_TEMPLATE := ../../../LICENSE_SHORT

.PHONY: help install fmt lint test unit-test integration-test

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install project dependencies via Poetry.
	poetry install

fmt:  ## Format source code with ruff and add missing Apache license headers.
	poetry run ruff format .
	poetry run ruff check . --fix

lint:  ## Lint source code with ruff.
	poetry run ruff check .

unit-test:  ## Run unit tests with pytest.
	poetry run pytest unit_tests

integration-test:  ## Run integration tests (mocked HTTP, real discover/read entrypoint) with pytest.
	poetry run pytest integration_tests

test: lint unit-test integration-test  ## Run lint checks, unit tests, and integration tests.

check:
	$(SCRIPT) check $(CONFIG)

discover:
	$(SCRIPT) discover $(CONFIG)

read:
	$(SCRIPT) read $(CONFIG) --catalog integration_tests/configured_catalog.json
