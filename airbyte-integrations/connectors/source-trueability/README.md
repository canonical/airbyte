# TrueAbility Source Connector

Declarative Airbyte source connector for the [TrueAbility AbilityScreen API](https://app.trueability.com/api/v1/docs) (`GET /api/v1/results`).

Each assessment attempt is emitted on the `results` stream with:
- `id`: numeric TrueAbility assessment ID (primary key)
- `payload`: raw assessment result object, including nested `scenario_tasks`, `commands`, `user_transcript`, and `assessment_files`

Before emitting a record, `components.py` removes direct candidate PII (`user_id`, `user_email`, `user_first_name`, `user_full_name`, `user_last_name`, `address`, and `user_transcript.summary.user`) and retains only `uuid` on `user` objects.

## Configuration

| Field | Required | Description |
| --- | --- | --- |
| `api_key` | Yes | API key sent in the `X-API-KEY` header. |
| `ability_screen_ids` | No | Restrict results to these numeric AbilityScreen (exam template) IDs (`ability_screen_id[]`). |
| `assessment_ids` | No | Restrict results to these numeric assessment attempt IDs (`id[]`). |
| `finalized_after` | No | RFC 3339 lower bound on assessment finalization time (`finalized_after`). |
| `finalized_before` | No | RFC 3339 upper bound on assessment finalization time (`finalized_before`). |
| `page_size` | No | Results requested per page (`per_page`, 1–500, default `50`). |

## Sync Behavior

- **Sync mode**: Full refresh only. `finalized_after` and `finalized_before` act as static query filters when configured, not incremental sync cursors.
- **Pagination**: Starts at page `1` and advances using `meta.current_page` and `meta.total_pages` until `current_page >= total_pages`. `TrueAbilityResultsExtractor` validates response pagination metadata against the requested page before yielding records.

## Local Development

Run unit tests and build/inspect the connector image locally:

```sh
make unit-test
make build
make spec
make discover CONFIG=integration_tests/sample_config.json
```

To test against a live TrueAbility environment, place credentials in `secrets/config.json` (gitignored):

```sh
make check
make read
make test
```
