# Kapa Source Connector

The Kapa source connector syncs project threads, end users, and analytics from the Kapa Query API v1. It is a manifest-only connector using API-key authentication, cursor and page pagination, and incremental state for threads.

For user-facing setup instructions, see the [Kapa source documentation](https://docs.airbyte.com/integrations/sources/kapa).

## Streams

| Stream                   | Primary key       | Cursor             | Sync modes                |
| ------------------------ | ----------------- | ------------------ | ------------------------- |
| `threads`                | `id`              | `last_activity_at` | Full refresh, incremental |
| `activity`               | None              | None               | Full refresh              |
| `top_questions_periods`  | `id`              | None               | Full refresh              |
| `top_questions_clusters` | `period_id`, `id` | None               | Full refresh              |
| `coverage_gaps_periods`  | `id`              | None               | Full refresh              |
| `coverage_gaps_clusters` | `period_id`, `id` | None               | Full refresh              |
| `end_users`              | `id`              | None               | Full refresh              |

Incremental requests send the saved cursor as the inclusive `updated_since` lower bound and sort by `last_activity_at` ascending. A record at the state boundary can be read again; append-dedup mode uses `id` to remove that boundary duplicate.

`activity` emits one record containing aggregate statistics and statistics grouped by integration for the range from `start_date` through the sync start time. The period streams return completed weekly, monthly, or quarterly analytics periods. Their cluster substreams make one paginated detail traversal per period and attach `period_id` and `analytics_interval` to each record.

Cluster records include inline thread summaries. Kapa returns at most 100 recent threads per cluster, so `thread_count` is authoritative when it exceeds the length of `threads`.

`end_users` uses full refresh and follows Kapa's numbered `next` page links. Records can contain personal and external identity data, including email addresses, company names, client identifiers, and identity-provider subject IDs. Apply destination access controls and retention policies appropriate for that data.

## Configuration

| Field                | Required | Description                                                                                                  |
| -------------------- | -------- | ------------------------------------------------------------------------------------------------------------ |
| `api_key`            | Yes      | Kapa API key sent in the `X-API-KEY` header.                                                                 |
| `project_id`         | Yes      | UUID of the Kapa project to sync.                                                                            |
| `start_date`         | Yes      | Earliest thread activity and aggregate activity timestamp, in ISO 8601 format with whole-second precision.   |
| `analytics_interval` | No       | Period size for Top Questions and Coverage Gaps: `weekly`, `monthly`, or `quarterly`. Defaults to `monthly`. |

Keep real credentials in `.secrets/config.json`. The tracked values under `integration_tests/` are non-production placeholders.

## Local Development

Run `make help` to list commands and input paths. The default authenticated configuration path is `.secrets/config.json`.

```bash
make build
make spec
make unit-test
make connector-test
```

Authenticated commands require a local config:

```bash
make check
make discover
make read
```

Override inputs when needed:

```bash
make read CONFIG=.secrets/config.json CATALOG=integration_tests/configured_catalog.json STATE=integration_tests/sample_state.json
```

## Docker Commands

After `make build`, the corresponding container commands are:

```bash
docker run --rm airbyte/source-kapa:dev spec
docker run --rm -v "$PWD/.secrets/config.json:/config.json:ro" airbyte/source-kapa:dev check --config /config.json
docker run --rm -v "$PWD/.secrets/config.json:/config.json:ro" airbyte/source-kapa:dev discover --config /config.json
docker run --rm \
  -v "$PWD/.secrets/config.json:/config.json:ro" \
  -v "$PWD/integration_tests/configured_catalog.json:/catalog.json:ro" \
  -v "$PWD/integration_tests/sample_state.json:/state.json:ro" \
  airbyte/source-kapa:dev read --config /config.json --catalog /catalog.json --state /state.json
```

## Tests

`unit_tests/` loads the real manifest through the CDK and mocks Kapa HTTP responses. It covers authentication, request parameters, pagination, incremental lower bounds, resource errors, rate limiting, and transient service errors.

`acceptance-test-config.yml` runs the manifest specification check. Run `make test` from an initialized `airbyte-ci/connectors/pipelines` Poetry environment.

## Known Limitations

- Analytics streams use full refresh because Kapa does not expose a correctness-safe incremental cursor for them.
- Cluster detail reads fan out once per completed period and can make many requests for projects with long analytics histories.
- Inline cluster threads are limited to 100 recent records; use `thread_count` for the true total.
- End-user records use full refresh because the API does not expose a correctness-safe incremental filter or cursor.
- Kapa does not document endpoint-specific rate limits or every error payload. The connector applies bounded fallback handling for 403 rate-limit responses, 429, and transient 502/503/504 responses.
- Expected integration records are not tracked because threads, end users, and analytics are specific to each Kapa project.
