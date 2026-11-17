# Local dev commands for source-ubuntu-archive-downloads.

CONNECTOR_NAME := source-ubuntu-archive-downloads
POETRY := poetry
SCRIPT := $(POETRY) run source-ubuntu-archive-downloads
CONFIG := --config integration_tests/mock_config.json
CATALOG := --catalog integration_tests/configured_catalog.json
LICENSE_TEMPLATE := ../../../LICENSE_SHORT
CDK := $(POETRY) run airbyte-cdk

.PHONY: help install fmt lint build spec check discover read unit-test integration-test test mock-archives

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

build:  ## Build the connector docker image (tagged airbyte/source-ubuntu-archive-downloads:dev).
	$(CDK) image build

spec:  ## Print the connector's connection specification.
	$(SCRIPT) spec

check:  ## Check the containers in CONFIG are readable (defaults to the mock config).
	$(SCRIPT) check $(CONFIG)

discover:  ## Discover one stream per package set in CONFIG.
	$(SCRIPT) discover $(CONFIG)

read:  ## Read records for the configured catalog (override CATALOG to use another file).
	$(SCRIPT) read $(CONFIG) $(CATALOG)

unit-test:  ## Run unit tests with pytest.
	poetry run pytest unit_tests

integration-test:  ## Run integration tests (real check/discover/read entrypoint over the mock archives) with pytest.
	poetry run pytest integration_tests

test: lint unit-test integration-test  ## Run lint checks, unit tests and integration tests against the mock archives.

mock-archives:  ## Regenerate the mock log containers in integration_tests/mock_archives.
	poetry run python integration_tests/generate_mock_archives.py
