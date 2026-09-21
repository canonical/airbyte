# Local dev commands for source-expensify.

CONNECTOR_NAME := source-expensify
POETRY := poetry
SCRIPT := $(POETRY) run source-expensify
CONFIG := --config secrets/config.json
CATALOG := --catalog integration_tests/configured_catalog.json
LICENSE_TEMPLATE := ../../../LICENSE_SHORT
CDK := $(POETRY) run airbyte-cdk

.PHONY: help install fmt lint build spec check discover read unit-test integration-test acceptance-test test

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

build:  ## Build the connector docker image (tagged airbyte/source-expensify:dev).
	$(CDK) image build

spec:  ## Print the connector's connection specification.
	$(SCRIPT) spec

check:  ## Validate the configured credentials in secrets/config.json.
	$(SCRIPT) check $(CONFIG)

discover:  ## Discover the available streams for the configured credentials.
	$(SCRIPT) discover $(CONFIG)

read:  ## Read records for the configured catalog (override CATALOG to use another file).
	$(SCRIPT) read $(CONFIG) $(CATALOG)

unit-test:  ## Run unit tests with pytest.
	poetry run pytest unit_tests

integration-test:  ## Run integration tests (mocked HTTP, real discover/read entrypoint) with pytest.
	poetry run pytest integration_tests

acceptance-test:  ## Run connector acceptance tests (see acceptance-test-config.yml) via airbyte-cdk.
	$(CDK) connector test

test: lint unit-test integration-test acceptance-test  ## Run lint checks, unit tests, integration tests, and connector acceptance tests.
