# Expensify source connector

This directory contains the implementation for `source-expensify`, a Python connector built on the Airbyte CDK.

For information about how to configure and use this connector within Airbyte, see [the connector's full documentation](https://docs.airbyte.com/integrations/sources/expensify).

## Streams

| Stream  | Primary Key | Cursor Field |
| ------- | ----------- | ------------ |
| Reports | `reportID`  | `updatedAt`  |

The `reports` stream exports Expensify report data (via the Integration Server's `combinedReportData` export) for reports in the configured `report_state`(s) (if unset, reports in all states are included).
Expensify has no native "last updated" column, so the connector derives the `updatedAt` cursor from the most recent non-null value across the `created`, `submitted`, `approved`, and `reimbursed` date columns on each row.

Incremental syncs resume the underlying Expensify export window from a secondary, internal `createdOrSubmittedAt` cursor (matching Expensify's own `startDate`/`endDate` export filter semantics, which only consider the `created`/`submitted` columns). Because a report can be approved or reimbursed well after it was created/submitted, strictly resuming from that cursor could permanently miss such late changes once the resumed window moves past the report's `created`/`submitted` date. To avoid this without a complex per-report state machine, the connector trails the resumed export window backward by a configurable `lookback_window_days` (default 30) on every incremental sync, replaying that trailing window so late-changing reports keep being re-exported and re-synced. The configured `start_date` always remains a hard lower bound, and widening `start_date` further into the past than the lookback window still requires a state reset (or a full refresh) to backfill that older data.

## Configuration

The connector requires the following configuration fields:

| Field                   | Description                                                                                                                                                                                                     | Required |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `partner_user_id`       | The Partner User ID, generated from the Expensify Integration Server credentials page.                                                                                                                        | Yes      |
| `partner_user_secret`   | The Partner User Secret, generated from the Expensify Integration Server credentials page.                                                                                                                    | Yes      |
| `start_date`            | The start date (inclusive) used to filter Expensify reports for export, in the format `YYYY-MM-DD`.                                                                                                           | Yes      |
| `end_date`              | The end date (inclusive) used to filter Expensify reports for export, in the format `YYYY-MM-DD`. If unset, there is no upper bound (up to today).                                                             | No       |
| `report_state`          | None or more of `OPEN`, `SUBMITTED`, `APPROVED`, `REIMBURSED`, `ARCHIVED`. If unset, reports in all states are included.                                                                                        | No       |
| `lookback_window_days`  | Number of days to trail the resumed incremental export window backward, to catch reports approved/reimbursed after their `created`/`submitted` date. Defaults to 30. Never goes earlier than `start_date`.    | No       |

## Local development

### Prerequisites

- Python (`^3.11`)
- Poetry (`^1.7`) - installation instructions [here](https://python-poetry.org/docs/#installation)

### Installing the connector

From this connector directory, run:

```bash
poetry install --with dev
```

### Create credentials

**If you are a community contributor**, follow the instructions in the [documentation](https://docs.airbyte.com/integrations/sources/expensify)
to generate the necessary credentials. Then create a file `secrets/config.json` conforming to the `spec.yaml` file in this connector's `source_expensify` directory, for example:

```json
{
  "partner_user_id": "<partner_user_id>",
  "partner_user_secret": "<partner_user_secret>",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31"
}
```

Note that any directory named `secrets` is gitignored across the entire Airbyte repo, so there is no danger of accidentally checking in sensitive information.

### Locally running the connector

```bash
poetry run source-expensify spec
poetry run source-expensify check --config secrets/config.json
poetry run source-expensify discover --config secrets/config.json
poetry run source-expensify read --config secrets/config.json --catalog integration_tests/configured_catalog.json
```

### Running unit tests

To run unit tests locally, from the connector directory run:

```bash
poetry run pytest unit_tests
```

### Building the docker image

This connector has no checked-in `Dockerfile`; its image is built from the `baseImage` declared in `metadata.yaml` using the `airbyte-cdk` CLI:

```bash
poetry run airbyte-cdk image build --tag dev
```

An image will be available on your host with the tag `airbyte/source-expensify:dev`.

### Running as a docker container

Then run any of the standard source connector commands:

```bash
docker run --rm airbyte/source-expensify:dev spec
docker run --rm -v $(pwd)/secrets:/secrets airbyte/source-expensify:dev check --config /secrets/config.json
docker run --rm -v $(pwd)/secrets:/secrets airbyte/source-expensify:dev discover --config /secrets/config.json
docker run --rm -v $(pwd)/secrets:/secrets -v $(pwd)/integration_tests:/integration_tests airbyte/source-expensify:dev read --config /secrets/config.json --catalog /integration_tests/configured_catalog.json
```
