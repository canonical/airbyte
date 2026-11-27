CONNECTOR := source-trueability
IMAGE ?= airbyte/$(CONNECTOR):dev
CONFIG ?= secrets/config.json
CATALOG ?= integration_tests/configured_catalog.json
PYTHON ?= 3.12
UV ?= uv

BASE_IMAGE := $(shell awk '/baseImage:/ {print $$2; exit}' metadata.yaml)
DOCKER_REPO := $(shell awk '/dockerRepository:/ {print $$2; exit}' metadata.yaml)
IMAGE_VERSION := $(shell awk '/dockerImageTag:/ {print $$2; exit}' metadata.yaml)
DOCKERFILE := ../../../docker-images/Dockerfile.manifest-only-connector

.PHONY: help build spec check discover read unit-test test

help: ## Show targets and input defaults.
	@printf 'Inputs: IMAGE=%s CONFIG=%s CATALOG=%s\n\n' "$(IMAGE)" "$(CONFIG)" "$(CATALOG)"
	@awk -F ':.*## ' '/^[a-z-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the local development Docker image.
	docker buildx build --load -f $(DOCKERFILE) -t "$(IMAGE)" \
		--label io.airbyte.name=$(DOCKER_REPO) \
		--label io.airbyte.version=$(IMAGE_VERSION) \
		--build-arg BASE_IMAGE=$(BASE_IMAGE) \
		--build-arg CONNECTOR_NAME=$(CONNECTOR) .

spec: ## Print the connector specification.
	docker run --rm "$(IMAGE)" spec

check: ## Check connection credentials using CONFIG.
	docker run --rm -v "$(abspath $(CONFIG)):/config.json:ro" "$(IMAGE)" check --config /config.json

discover: ## Discover stream schemas using CONFIG.
	docker run --rm -v "$(abspath $(CONFIG)):/config.json:ro" "$(IMAGE)" discover --config /config.json

read: ## Run a full-refresh read using CONFIG and CATALOG.
	docker run --rm -v "$(abspath $(CONFIG)):/config.json:ro" -v "$(abspath $(CATALOG)):/catalog.json:ro" \
		"$(IMAGE)" read --config /config.json --catalog /catalog.json

unit-test: ## Run offline unit tests with mocked HTTP responses.
	$(UV) run --isolated --python $(PYTHON) \
		--with 'airbyte-cdk==7.21.1' \
		--with 'pytest>=8,<9' \
		--with 'pytest-mock>=3.14,<4' \
		--with 'requests-mock>=1.12,<2' \
		pytest unit_tests -q

test: ## Run Connector Acceptance Tests via airbyte-cdk.
	$(UV) run --isolated --python $(PYTHON) --with 'airbyte-cdk[dev]==7.21.1' \
		airbyte-cdk connector test $(CURDIR)
