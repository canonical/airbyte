IMAGE = airbyte/source-udemy:dev
CONFIG = secrets/config.json
CATALOG = integration_tests/configured_catalog.json

.PHONY: build check discover read test

build:
	airbyte-cdk image build . --tag dev

check: 
	docker run --rm -v "$(PWD)/$(CONFIG):/$(CONFIG)" $(IMAGE) check --config /$(CONFIG)

discover:
	docker run --rm -v "$(PWD)/$(CONFIG):/$(CONFIG)" $(IMAGE) discover --config /$(CONFIG)

# Note: stream `courses` returns 28k+ records and has no filtering parameters to limit that
# Running `make read` with this stream can take a very long time
read:
	docker run --rm \
		-v "$(PWD)/$(CONFIG):/$(CONFIG)" \
		-v "$(PWD)/$(CATALOG):/$(CATALOG)" \
		$(IMAGE) read --config /$(CONFIG) --catalog /$(CATALOG)

## Run acceptance tests locally with airbyte-cdk (swaps in acceptance-test-config.local.yml)
# Note: run `make build` before this to ensure the latest image is used
test:
	./scripts/run-acceptance-tests.sh
