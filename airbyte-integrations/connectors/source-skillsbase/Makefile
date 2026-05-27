# Reusable commands for local dev and testing of source-skillsbase.
#
# Conventions:
#   - Real Skills Base credentials live in ./secrets/config.json (gitignored).
#   - integration_tests/invalid_config.json holds an intentionally-bad config.
#   - integration_tests/configured_catalog.json lists every supported stream.
#   - integration_tests/qualifications_catalog.json is the smallest catalog
#     (just qualifications_assignments) for quick end-to-end sync checks.
#
# Token caching: Skills Base limits the number of concurrent active access
# tokens, so each authenticated run is piped through scripts/persist_token.sh
# which writes the CDK's CONNECTOR_CONFIG control message back into
# secrets/config.json. That way the next invocation reuses the cached token
# instead of requesting a new one and getting 'Access token allowance exceeded'.

SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c

CONNECTOR  := source-skillsbase
IMAGE      := airbyte/$(CONNECTOR):dev
BASE_IMAGE := $(shell awk '/baseImage:/ {print $$2; exit}' metadata.yaml)
DOCKERFILE := ../../../docker-images/Dockerfile.manifest-only-connector

DOCKER_RUN := docker run --rm -v "$(CURDIR):/work" $(IMAGE)
CONFIG     := /work/secrets/config.json
INVALID    := /work/integration_tests/invalid_config.json
CATALOG    := /work/integration_tests/configured_catalog.json
QA_CATALOG := /work/integration_tests/qualifications_catalog.json

PERSIST := scripts/persist_token.sh secrets/config.json

.PHONY: help build spec check check-invalid discover read read-qualifications test-acceptance clean

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  %-22s %s\n", $$1, $$2}'

DOCKER_REPO    := $(shell awk '/dockerRepository:/ {print $$2; exit}' metadata.yaml)
IMAGE_VERSION  := $(shell awk '/dockerImageTag:/ {print $$2; exit}' metadata.yaml)

build:  ## Build the dev Docker image from this connector's manifest.
	docker buildx build --load \
	  -f $(DOCKERFILE) \
	  -t $(IMAGE) \
	  --label io.airbyte.name=$(DOCKER_REPO) \
	  --label io.airbyte.version=$(IMAGE_VERSION) \
	  --build-arg BASE_IMAGE=$(BASE_IMAGE) \
	  --build-arg CONNECTOR_NAME=$(CONNECTOR) \
	  .

spec:  ## Print the connector spec JSON.
	docker run --rm $(IMAGE) spec

gen-spec:  ## Generate integration_tests/spec.json (the expected ConnectorSpecification CAT compares against).
	@docker run --rm $(IMAGE) spec \
	  | jq -c 'select(.type == "SPEC") | .spec' \
	  | jq '.' \
	  > integration_tests/spec.json
	@echo "✅ Wrote integration_tests/spec.json. Re-run after any change to manifest.yaml's spec section."

check:  ## Run check against secrets/config.json (expect succeed). Persists the refreshed token.
	$(DOCKER_RUN) check --config $(CONFIG) | $(PERSIST)

check-invalid:  ## Run check against integration_tests/invalid_config.json (expect fail). No persist.
	$(DOCKER_RUN) check --config $(INVALID)

discover:  ## Discover available streams. Persists the refreshed token.
	$(DOCKER_RUN) discover --config $(CONFIG) | $(PERSIST)

read:  ## Read all streams using configured_catalog.json. Persists the refreshed token.
	$(DOCKER_RUN) read --config $(CONFIG) --catalog $(CATALOG) | $(PERSIST)

read-qualifications:  ## Read only qualifications_assignments (smallest stream, ~15 records on sandbox). Persists the refreshed token.
	$(DOCKER_RUN) read --config $(CONFIG) --catalog $(QA_CATALOG) | $(PERSIST)

test-acceptance: build  ## Run Connector Acceptance Tests via the official Docker image (rebuilds image and pre-warms token first).
	# Pre-warm the access_token cache so the parallel CAT containers reuse it
	# instead of each calling /oauth/access_token and tripping Skills Base's
	# concurrent-token allowance.
	$(DOCKER_RUN) check --config $(CONFIG) | $(PERSIST)
	# CAT's backward-compatibility fixture (test_backward_compatibility) tries
	# to docker-pull $(DOCKER_REPO):latest from Docker Hub at setup time, which
	# fails for Canonical-only connectors that aren't published there. Deselect
	# those tests at pytest collection time so the fixture never runs.
	docker run --rm \
	  -v "$(CURDIR):/test_input" \
	  -v /var/run/docker.sock:/var/run/docker.sock \
	  -e PYTEST_ADDOPTS="-k 'not test_backward_compatibility'" \
	  airbyte/connector-acceptance-test:latest \
	  --acceptance-test-config /test_input

clean:  ## Remove the local dev Docker image.
	-docker rmi $(IMAGE)
