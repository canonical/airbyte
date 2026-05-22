# Source Udemy

Manifest-only Airbyte source connector for [Udemy Business](https://business.udemy.com/).

Official organization API documentation:
https://canonical.udemy.com/developers/organization/

## Streams

| Stream                 | Sync Mode    | Endpoint                                                                  | Date filtering         |
|------------------------|--------------|---------------------------------------------------------------------------|------------------------|
| `courses`              | Full Refresh | `GET /api-2.0/organizations/{account_id}/courses/list/`                   | None                   |
| `learning_paths`       | Full Refresh | `GET /api-2.0/organizations/{account_id}/learning-paths/list/`            | None                   |
| `user_activity`        | Full Refresh | `GET /api-2.0/organizations/{account_id}/analytics/user-activity/`        | `from_date`, `to_date` |
| `user_path_activity`   | Full Refresh | `GET /api-2.0/organizations/{account_id}/analytics/user-path-activity/`   | None                   |
| `user_course_activity` | Full Refresh | `GET /api-2.0/organizations/{account_id}/analytics/user-course-activity/` | `from_date`, `to_date` |

> **Note:** The Udemy Business API supports additional query parameters for filtering by course ID or user email on some endpoints. These are intentionally omitted — the connector ingests full datasets, and filtering should be applied in the destination.

## Authentication

Uses HTTP Basic Auth with a Udemy Business API **Client ID** (username) and **Client Secret** (password).
Generate credentials in your Udemy Business admin panel under **Settings → API**.

## Configuration

| Field           | Required | Description                                                                                      |
|-----------------|----------|--------------------------------------------------------------------------------------------------|
| `account_name`  | Yes      | Your company subdomain, e.g. `canonical` from `https://canonical.udemy.com`                     |
| `account_id`    | Yes      | Your company account ID (visible in the Udemy Business admin panel)                              |
| `client_id`     | Yes      | API client ID                                                                                    |
| `client_secret` | Yes      | API client secret                                                                                |
| `from_date`     | No       | Filter `user_activity` and `user_course_activity` from this date (format: `YYYY-MM-DD`). Affects aggregations and statistics, not a parameter for incremental sync. Can be used for fast iterations, e.g. for tests.         |
| `to_date`       | No       | Filter `user_activity` and `user_course_activity` up to this date (format: `YYYY-MM-DD`). Affects aggregations and statistics, not a parameter for incremental sync. Can be used for fast iterations, e.g. for tests.        |
| `page_size`     | No       | Records per page for paginated requests. Defaults to `20`, maximum `100`.                        |

## Local development

### Prerequisites

- Docker
- [`airbyte-cdk`](https://pypi.org/project/airbyte-cdk/) CLI

### Credentials

Create `secrets/config.json`:

```json
{
  "account_name": "<your-subdomain>",
  "account_id": "<your-account-id>",
  "client_id": "<your-client-id>",
  "client_secret": "<your-client-secret>",
  "from_date": "2025-01-01", // optional
  "to_date": "2025-12-31", // optional
  "page_size": 20 // optional
}
```

### Makefile commands

All commands are run from the connector root directory.

| Command         | What it does                                                                                                                                                                       |
|-----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `make build`    | Builds `airbyte/source-udemy:dev` via `airbyte-cdk image build`, which generates a Dockerfile and invokes `docker buildx`                                                          |
| `make check`    | Runs `check` inside the built image against `secrets/config.json` to validate credentials                                                                                          |
| `make discover` | Runs `discover` inside the built image and prints the stream catalog                                                                                                               |
| `make read`     | Runs `read` inside the built image using `integration_tests/configured_catalog.json` (all streams)                                                                                 |
| `make test`     | Runs `scripts/run-acceptance-tests.sh`, which uses `poe install-cdk-cli` to ensure the CDK CLI is available, then runs `airbyte-cdk connector test` (requires `make build` first) |

> **Note:** `make build` must be run before `make check`, `make discover`, `make read`, or `make test`.

> **Note:** The `courses` stream returns 28 000+ records and has no date filtering. `make read` with `courses` in the catalog can take a long time. For faster local iteration, edit `CATALOG` in the Makefile to point to `integration_tests/configured_catalog.local.json`, which excludes `courses`.

### Running acceptance tests

```bash
make build
make test
```

The test command automatically swaps in `acceptance-test-config.local.yml`, which excludes `courses` via `empty_streams` so tests complete in a reasonable time.
