---
name: python-cdk-connector
description: Scaffolds a new Python CDK (non-manifest) Airbyte source connector in Canonical's Airbyte fork, following the layout of source-expensify. Generates metadata.yaml (with canonicalImageTag), pyproject.toml, spec.yaml, configured catalogs, schemas, source/stream boilerplate, Makefile, acceptance-test config, README and tests. Use when a developer asks to create, bootstrap or scaffold a new custom Python Airbyte connector.
---

# Python CDK Airbyte connector scaffold (Canonical standards)

This skill creates a new **Python CDK** source connector under
`airbyte-integrations/connectors/source-<slug>/`. The reference implementation is
`airbyte-integrations/connectors/source-expensify/`. Read it when you need a fuller example
(chunked exports, incremental state, lookback windows, error mapping).

Use a Python CDK connector only when the API cannot reasonably be expressed as a low-code
`manifest.yaml` (for example, multi-step export/download flows, non-JSON payloads, or custom
auth). For simple REST APIs, recommend a manifest-only connector instead and stop.

## Step 1: Gather details from the developer

Before you write any file, ask the developer for every value below in **one** batch of
questions. Use the question tool if it is available. Do not invent values. If the developer
doesn't know a value, use the default shown and mark it in the final summary.

| Placeholder | Question | Default / rule |
| --- | --- | --- |
| `{{display_name}}` | Human-readable connector name (e.g. "Expensify") | required |
| `{{slug}}` | Kebab-case slug (e.g. `expensify`) | derive from display name |
| `{{package}}` | Python package name | `source_{{slug with _}}` |
| `{{class_name}}` | Source class name | `Source{{PascalCase}}` |
| `{{api_docs_url}}` | Link to the API reference docs | required |
| `{{api_base_url}}` | Base URL of the API | required |
| `{{allowed_hosts}}` | Host names the connector calls (no scheme) | host of `{{api_base_url}}` |
| `{{auth_type}}` | Auth method (API key header, bearer token, basic, OAuth2 client credentials, custom body credentials…) | required |
| `{{config_fields}}` | Config fields: name, type, required?, secret?, description, example | required |
| `{{streams}}` | For each stream: name, endpoint/path, primary key, cursor field (if incremental), pagination style | required |
| `{{check_endpoint}}` | Cheap endpoint to validate credentials in `check` | first stream endpoint |
| `{{start_date}}` | Does the connector need a `start_date` / `end_date`? Format? | `start_date` as `YYYY-MM-DD` |
| `{{author_name}}` / `{{author_email}}` | Author for `pyproject.toml` | from `git config user.name/email` |
| `{{jira_ticket}}` | Jira ticket (e.g. `CSS-12345`) for branch / commit names | optional |
| `{{version}}` | Initial connector version | `0.1.0` |
| `{{canonical_version}}` | Canonical fork version suffix | `1.0.0` |
| `{{release_stage}}` | `alpha`, `beta` or `generally_available` | `alpha` |

Then derive:

- `{{definition_id}}`: a new UUID4 (`python -c "import uuid; print(uuid.uuid4())"`). Check it
  isn't already used: `grep -r <uuid> airbyte-integrations/connectors/*/metadata.yaml`.
- `{{year}}`: the current year.
- `{{today}}`: today's date, `YYYY-MM-DD`.

Confirm the derived values with the developer, and check that
`airbyte-integrations/connectors/source-{{slug}}/` doesn't already exist.

## Step 2: Create the directory layout

```
airbyte-integrations/connectors/source-{{slug}}/
├── Makefile
├── README.md
├── acceptance-test-config.yml
├── main.py
├── metadata.yaml
├── pyproject.toml
├── integration_tests/
│   ├── __init__.py
│   ├── abnormal_state.json
│   ├── configured_catalog.json
│   ├── configured_catalog_incremental.json   # only if any stream is incremental
│   ├── invalid_config.json
│   ├── sample_config.json
│   └── sample_state.json                     # only if any stream is incremental
├── secrets/                                  # git-ignored; never commit
│   └── config.json
├── {{package}}/
│   ├── __init__.py
│   ├── base_stream.py
│   ├── run.py
│   ├── source.py
│   ├── spec.yaml
│   ├── <stream>.py                           # one module per stream
│   └── schemas/
│       └── <stream>.json                     # one schema per stream
└── unit_tests/
    ├── __init__.py
    └── test_<stream>.py
```

## Step 3: Fill in the files

Replace every `{{placeholder}}`. Remove optional blocks that don't apply.

### `metadata.yaml`

The Canonical fork **requires** `canonicalImageTag`. Its format is
`<dockerImageTag>-canonical-<canonical_version>`. The `Canonical Check Image Version`
workflow fails any PR that touches a connector without changing this value.

```yaml
data:
  allowedHosts:
    hosts:
      - "{{allowed_hosts}}"
  registryOverrides:
    oss:
      enabled: true
    cloud:
      enabled: true
  remoteRegistries:
    pypi:
      enabled: false
      packageName: airbyte-source-{{slug}}
  connectorBuildOptions:
    baseImage: docker.io/airbyte/python-connector-base:4.1.1@sha256:a268b44c733ae699a60f5fbc06a324945dba98945c6e2ab7f8609f2f895b0d28
  connectorSubtype: api
  connectorType: source
  definitionId: {{definition_id}}
  dockerImageTag: {{version}}
  canonicalImageTag: {{version}}-canonical-{{canonical_version}}
  dockerRepository: airbyte/source-{{slug}}
  githubIssueLabel: source-{{slug}}
  icon: {{slug}}.svg
  license: ELv2
  name: {{display_name}}
  releaseDate: {{today}}
  releaseStage: {{release_stage}}
  supportLevel: community
  documentationUrl: https://docs.airbyte.com/integrations/sources/{{slug}}
  tags:
    - language:python
  ab_internal:
    ql: 100
    sl: 100
  connectorTestSuitesOptions:
    - suite: acceptanceTests
      testSecrets:
        - name: SECRET_SOURCE-{{SLUG_UPPER}}__CREDS
          fileName: config.json
          secretStore:
            type: GSM
            alias: airbyte-connector-testing-secret-store
  externalDocumentationUrls:
    - title: {{display_name}} API reference
      url: {{api_docs_url}}
      type: api_reference
metadataSpecVersion: "1.0"
```

Before you use the `baseImage` digest above, check that it is still the one used by other
recent Python connectors in the repo (`grep -h python-connector-base */metadata.yaml | sort | uniq -c`)
and use the most common recent one.

### `pyproject.toml`

`[tool.poetry].version` **must equal** `dockerImageTag`.

```toml
[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"

[tool.poetry]
version = "{{version}}"
name = "source-{{slug}}"
description = "Source implementation for {{display_name}}."
authors = ["{{author_name}} <{{author_email}}>"]
readme = "README.md"
homepage = "https://airbyte.com"
repository = "https://github.com/canonical/airbyte"
[[tool.poetry.packages]]
include = "{{package}}"

[tool.poetry.dependencies]
python = ">=3.11,<3.14"
airbyte-cdk = ">=7.28.3,<8.0.0"

[tool.poetry.scripts]
source-{{slug}} = "{{package}}.run:run"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
pytest-mock = "^3.6.1"
freezegun = "^1.5.5"
requests-mock = "^1.12.1"
ruff = "0.8.3"

[tool.poe]
include = [
    # Shared tasks definition file(s) can be imported here.
    # Run `poe` or `poe --help` to see the list of available tasks.
    "${POE_GIT_DIR}/poe-tasks/poetry-connector-tasks.toml",
]
```

### `{{package}}/spec.yaml`

Generate one property per config field the developer listed. Rules:

- Every credential field gets `airbyte_secret: true`.
- Every field gets `title`, `description` and an `order` (0-based, in the order given).
- Date fields use `pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"` and an `examples` entry.
- Optional fields with defaults declare `default`.
- Keep `additionalProperties: true`.

```yaml
documentationUrl: https://docs.airbyte.com/integrations/sources/{{slug}}
connectionSpecification:
  $schema: http://json-schema.org/draft-07/schema#
  title: {{display_name}} Spec
  type: object
  required:
    - api_key        # replace with the developer's required fields
    - start_date
  additionalProperties: true
  properties:
    api_key:
      type: string
      title: API Key
      description: The API key used to authenticate with the {{display_name}} API. See {{api_docs_url}}.
      airbyte_secret: true
      order: 0
    start_date:
      type: string
      title: Start Date
      description: >-
        The start date (inclusive) from which to replicate data, in the format YYYY-MM-DD.
      pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
      examples:
        - "{{today}}"
      order: 1
```

### `main.py`

```python
# Copyright (c) {{year}} Airbyte, Inc., all rights reserved.

from {{package}}.run import run


if __name__ == "__main__":
    run()
```

### `{{package}}/run.py`

```python
# Copyright (c) {{year}} Airbyte, Inc., all rights reserved.

import sys

from airbyte_cdk.entrypoint import launch
from {{package}}.source import {{class_name}}


def run():
    source = {{class_name}}()
    launch(source, sys.argv[1:])
```

### `{{package}}/__init__.py`

```python
# Copyright (c) {{year}} Airbyte, Inc., all rights reserved.

from .source import {{class_name}}


__all__ = ["{{class_name}}"]
```

### `{{package}}/base_stream.py`

Shared HTTP, retry and error-mapping logic for all streams. Adapt the auth headers and the
pagination to what the developer described. Keep the error-handling contract:

- HTTP 429 → `UserDefinedBackoffException` (fixed backoff, retried)
- HTTP 5xx → `DefaultBackoffException` (exponential backoff, retried), then
  `AirbyteTracedException(failure_type=transient_error)`
- HTTP 401/403 → `CredentialsInvalidError`, surfaced as `config_error`
- Other 4xx → `AirbyteTracedException(failure_type=config_error)`

```python
# Copyright (c) {{year}} Airbyte, Inc., all rights reserved.

"""Shared ingestion logic for {{display_name}} streams."""

from typing import Any, Iterable, List, Mapping, Optional

import requests

from airbyte_cdk.models import FailureType, SyncMode
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http.exceptions import DefaultBackoffException, UserDefinedBackoffException
from airbyte_cdk.sources.streams.http.rate_limiting import default_backoff_handler, user_defined_backoff_handler
from airbyte_cdk.utils.traced_exception import AirbyteTracedException


API_BASE_URL = "{{api_base_url}}"

MAX_RETRIES = 5
RETRY_FACTOR = 5
RATE_LIMIT_BACKOFF_SECONDS = 10.0
REQUEST_TIMEOUT_SECONDS = 60


class CredentialsInvalidError(Exception):
    """Raised when the {{display_name}} credentials are invalid (HTTP 401/403)."""


class ResourceNotFoundError(Exception):
    """Raised when the requested {{display_name}} resource doesn't exist (HTTP 404)."""


def _map_response_code_to_exception(response_code: int) -> None:
    if response_code in (requests.codes.unauthorized, requests.codes.forbidden):
        raise CredentialsInvalidError("{{display_name}} credentials are invalid.")
    if response_code == requests.codes.not_found:
        raise ResourceNotFoundError("{{display_name}} resource not found.")
    if response_code >= 500:
        raise AirbyteTracedException(
            internal_message=f"{{display_name}} returned server error response code {response_code}.",
            message=f"{{display_name}} API request failed with a server error (code {response_code}). This is likely transient, please try again later.",
            failure_type=FailureType.transient_error,
        )
    if response_code >= requests.codes.bad_request:
        raise AirbyteTracedException(
            internal_message=f"{{display_name}} returned client error response code {response_code}.",
            message=f"{{display_name}} API request failed with client error (code {response_code}). Please verify your configuration.",
            failure_type=FailureType.config_error,
        )


@user_defined_backoff_handler(max_tries=MAX_RETRIES)
@default_backoff_handler(max_tries=MAX_RETRIES, factor=RETRY_FACTOR)
def _send_request(
    method: str,
    path: str,
    headers: Mapping[str, str],
    params: Optional[Mapping[str, Any]] = None,
    json_body: Optional[Mapping[str, Any]] = None,
) -> requests.Response:
    """Send a request, retrying 429s with a fixed backoff and 5xx/connection errors exponentially."""
    response = requests.request(
        method,
        f"{API_BASE_URL}{path}",
        headers=headers,
        params=params,
        json=json_body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == requests.codes.too_many_requests:
        raise UserDefinedBackoffException(backoff=RATE_LIMIT_BACKOFF_SECONDS, request=response.request, response=response)
    if response.status_code >= 500:
        raise DefaultBackoffException(request=response.request, response=response)
    if response.status_code >= requests.codes.bad_request:
        _map_response_code_to_exception(response.status_code)
    return response


def build_auth_headers(config: Mapping[str, Any]) -> Mapping[str, str]:
    # Adapt to {{auth_type}}.
    return {"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"}


class {{PascalCase}}Stream(Stream):
    """
    Base class for {{display_name}} streams.

    Subclasses must declare:
      - `primary_key`: the field(s) that uniquely identify a record.
      - `path`: the API path for this stream.
      - `cursor_field` (optional): the field used for incremental syncs.
    """

    primary_key: Any = None
    path: str = ""
    cursor_field: str = ""

    def __init__(self, name: str, config: Mapping[str, Any], **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self.config = config
        self.start_date = config.get("start_date")

    @property
    def name(self) -> str:
        return self._name

    def get_updated_state(self, current_stream_state: Mapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.cursor_field:
            return {}
        candidates = [v for v in ((current_stream_state or {}).get(self.cursor_field), latest_record.get(self.cursor_field)) if v]
        return {self.cursor_field: max(candidates)} if candidates else dict(current_stream_state or {})

    def request_params(self, stream_state: Optional[Mapping[str, Any]], next_page_token: Optional[Any]) -> Mapping[str, Any]:
        # Adapt to the API's filtering and pagination parameters.
        params = {}
        if next_page_token:
            params["page"] = next_page_token
        return params

    def next_page_token(self, response: requests.Response) -> Optional[Any]:
        # Adapt to the API's pagination style. Return None when there are no more pages.
        return None

    def parse_response(self, response: requests.Response) -> Iterable[Mapping[str, Any]]:
        # Adapt to the API's response envelope.
        yield from response.json()

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        self.logger.info(f"Reading records from {{display_name}} for {self.name}")
        state = stream_state if sync_mode == SyncMode.incremental else None
        next_page_token = None
        record_count = 0
        while True:
            response = _send_request(
                "GET", self.path, headers=build_auth_headers(self.config), params=self.request_params(state, next_page_token)
            )
            for record in self.parse_response(response):
                record_count += 1
                yield record
            next_page_token = self.next_page_token(response)
            if not next_page_token:
                break
        self.logger.info(f"Read {record_count} record(s) for {self.name}.")
```

### `{{package}}/<stream>.py` (one per stream)

```python
# Copyright (c) {{year}} Airbyte, Inc., all rights reserved.

from {{package}}.base_stream import {{PascalCase}}Stream


class {{PascalCase}}{{StreamPascal}}Stream({{PascalCase}}Stream):
    primary_key = "{{stream_primary_key}}"
    path = "{{stream_path}}"
    cursor_field = "{{stream_cursor_field}}"   # remove for full-refresh-only streams
```

### `{{package}}/source.py`

```python
# Copyright (c) {{year}} Airbyte, Inc., all rights reserved.

from typing import Any, List, Mapping, Tuple

from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from {{package}}.base_stream import CredentialsInvalidError, _send_request, build_auth_headers
from {{package}}.{{stream_module}} import {{PascalCase}}{{StreamPascal}}Stream


class {{class_name}}(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, Any]:
        try:
            _send_request("GET", "{{check_endpoint}}", headers=build_auth_headers(config))
            return True, None
        except CredentialsInvalidError:
            logger.info("Credentials are invalid.")
            return False, "Credentials are invalid. Please verify your {{display_name}} credentials."
        except Exception as e:
            logger.info(f"Other issue connecting to {{display_name}}: {e}")
            return False, e

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        return [
            {{PascalCase}}{{StreamPascal}}Stream(name="{{stream_name}}", config=config),
        ]
```

### `{{package}}/schemas/<stream>.json`

Build the schema from the API docs (or a sample response). Every property is nullable.
Include the primary key and cursor field.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": true,
  "properties": {
    "id": { "type": ["null", "string"] },
    "updated_at": { "type": ["null", "string"], "format": "date-time" }
  }
}
```

### `integration_tests/configured_catalog.json`

One entry per stream, full refresh:

```json
{
  "streams": [
    {
      "stream": {
        "name": "{{stream_name}}",
        "json_schema": {},
        "supported_sync_modes": ["full_refresh"],
        "source_defined_primary_key": [["{{stream_primary_key}}"]]
      },
      "sync_mode": "full_refresh",
      "destination_sync_mode": "overwrite"
    }
  ]
}
```

### `integration_tests/configured_catalog_incremental.json` (incremental streams only)

```json
{
  "streams": [
    {
      "stream": {
        "name": "{{stream_name}}",
        "json_schema": {},
        "supported_sync_modes": ["full_refresh", "incremental"],
        "source_defined_cursor": true,
        "default_cursor_field": ["{{stream_cursor_field}}"],
        "source_defined_primary_key": [["{{stream_primary_key}}"]]
      },
      "sync_mode": "incremental",
      "cursor_field": ["{{stream_cursor_field}}"],
      "destination_sync_mode": "append_dedup",
      "primary_key": [["{{stream_primary_key}}"]]
    }
  ]
}
```

### Other `integration_tests/` files

- `sample_config.json`: every config field with obviously fake values
  (`"test-api-key"`) and real-looking dates.
- `invalid_config.json`: same keys, invalid credentials (`"invalid-api-key"`).
- `sample_state.json` / `abnormal_state.json` (incremental only), using per-stream state:

  ```json
  [
    {
      "type": "STREAM",
      "stream": {
        "stream_descriptor": { "name": "{{stream_name}}" },
        "stream_state": { "{{stream_cursor_field}}": "2100-01-01T00:00:00+00:00" }
      }
    }
  ]
  ```

  `abnormal_state.json` uses a far-future date. `sample_state.json` uses a recent date.

### `acceptance-test-config.yml`

```yaml
# See [Connector Acceptance Tests](https://docs.airbyte.com/connector-development/testing-connectors/connector-acceptance-tests-reference)
# for more information about how to configure these tests.
#
# Run these with `make acceptance-test` (or `make test`), which invokes
# `airbyte-cdk connector test`. The `connection` and `basic_read` scenarios below require a
# valid `secrets/config.json` (see README.md for how to obtain one).
connector_image: airbyte/source-{{slug}}:dev
acceptance_tests:
  spec:
    tests:
      - spec_path: "{{package}}/spec.yaml"
  connection:
    tests:
      - config_path: "secrets/config.json"
        status: "succeed"
      - config_path: "integration_tests/invalid_config.json"
        status: "failed"
  basic_read:
    tests:
      - config_path: "secrets/config.json"
        configured_catalog_path: "integration_tests/configured_catalog.json"
        empty_streams: []
```

### `Makefile`

Use tabs for recipe indentation.

```makefile
# Local dev commands for source-{{slug}}.

CONNECTOR_NAME := source-{{slug}}
POETRY := poetry
SCRIPT := $(POETRY) run source-{{slug}}
CONFIG := --config secrets/config.json
CATALOG := --catalog integration_tests/configured_catalog.json
CDK := $(POETRY) run airbyte-cdk

.PHONY: help install fmt lint build spec check discover read unit-test integration-test acceptance-test test

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install project dependencies via Poetry.
	poetry install

fmt:  ## Format source code with ruff.
	poetry run ruff format .
	poetry run ruff check . --fix

lint:  ## Lint source code with ruff.
	poetry run ruff check .

build:  ## Build the connector docker image (tagged airbyte/source-{{slug}}:dev).
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

integration-test:  ## Run integration tests with pytest.
	poetry run pytest integration_tests

acceptance-test:  ## Run connector acceptance tests via airbyte-cdk.
	$(CDK) connector test

test: lint unit-test integration-test acceptance-test  ## Run lint, unit, integration and acceptance tests.
```

### `unit_tests/test_<stream>.py`

Write tests with `requests_mock` (no real network calls) that cover at least:

1. `spec` loads and lists the required fields.
2. `check_connection` returns `(True, None)` on 200 and `(False, …)` on 401.
3. `read_records` yields parsed records for one page, then across several pages.
4. 429 is retried, then succeeds (patch `RATE_LIMIT_BACKOFF_SECONDS` to 0 or use `freezegun`).
5. 5xx is retried, then raises `AirbyteTracedException` with `FailureType.transient_error`.
6. Other 4xx raise `AirbyteTracedException` with `FailureType.config_error`.
7. For incremental streams: `get_updated_state` keeps the max cursor value.

### `README.md`

Include these sections: a short intro, **Streams** (table: stream, primary key, cursor field),
**Configuration** (table: field, description, required), **Local development**
(prerequisites: Python `^3.11`, Poetry; `make install`, `make spec/check/discover/read`),
**Testing** (`make unit-test`, `make acceptance-test`), and **Versioning** (explain the
three version values below). Link `{{api_docs_url}}`.

### `secrets/config.json`

Create the file with placeholder values only and confirm `secrets/` is git-ignored
(`git check-ignore airbyte-integrations/connectors/source-{{slug}}/secrets/config.json`).
**Never** write real credentials to it yourself, and never print the file's contents. Tell the
developer to fill it in.

## Step 4: Versioning rules (Canonical fork)

These three values must always stay in sync:

| Location | Field | Example |
| --- | --- | --- |
| `pyproject.toml` | `[tool.poetry].version` | `0.1.0` |
| `metadata.yaml` | `dockerImageTag` | `0.1.0` |
| `metadata.yaml` | `canonicalImageTag` | `0.1.0-canonical-1.0.0` |

- Any later PR that changes connector code, schemas, spec or dependencies must bump all
  three together. CI (`.github/workflows/canonical_check_version_increase.yml`) fails if
  `canonicalImageTag` is unchanged.
- Images are built and pushed by `.github/workflows/canonical_generate_image.yml`, which
  uses `canonicalImageTag` as the GHCR tag.
- See `.github/instructions/canonical.instructions.md` for the full rules.

## Step 5: Verify

Run these from the connector directory and report the results:

```bash
poetry install
poetry lock --check || poetry lock
make fmt
make lint
make spec
make unit-test
```

If the developer has filled in `secrets/config.json`, also run `make check`, `make discover`
and `make read`. If the developer has Docker, also run `make build` and `make acceptance-test`.

Do not say the scaffold works if you didn't run these commands. List the commands you skipped
and explain why.

## Step 6: Final summary

Finish with:

1. The list of files created.
2. A **version sync status** line: `pyproject.toml` version, `dockerImageTag`,
   `canonicalImageTag`, and confirmation that they match.
3. Any values that used a default or a guess (schemas, pagination, auth), which the developer
   must review.
4. Remaining TODOs: add `{{slug}}.svg` icon, fill `secrets/config.json`, add the GSM test
   secret `SECRET_SOURCE-{{SLUG_UPPER}}__CREDS`, open a PR (branch name prefixed with
   `{{jira_ticket}}` if given).
