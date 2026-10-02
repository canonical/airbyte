# NetSuite SuiteQL Source

This connector runs user-defined SuiteQL queries through NetSuite REST web
services. Each named query is exposed as a separate Airbyte stream.

This is separate from `source-netsuite`, which discovers and reads NetSuite
objects through the Record API. SuiteQL has a different endpoint, response
shape, schema-discovery strategy, and configuration workflow.

## Supports: 

- NetSuite token-based OAuth 1 authentication with HMAC-SHA256
- Multiple named SuiteQL queries in one source configuration
- Anonymous bound query parameters
- Offset pagination with a configurable page size
- Runtime JSON schema inference from the first returned row
- Full-refresh syncs
- Incremental syncs with deduplication

## Configuration

The connector requires an enabled NetSuite REST Web Services integration and a
token-based authentication access token with permission to query the requested
records.

| Field | Required | Description |
| --- | --- | --- |
| `realm` | Yes | NetSuite account ID, such as `2344535` or `2344535_SB1`. |
| `consumer_key` | Yes | Integration consumer key. |
| `consumer_secret` | Yes | Integration consumer secret. |
| `token_key` | Yes | Access token ID. |
| `token_secret` | Yes | Access token secret. |
| `queries` | Yes | One or more named SuiteQL queries. |
| `page_size` | No | Rows requested per page, from 1 to 1000. Defaults to 1000. |

Query names must be unique valid Airbyte stream names: they must start with a
letter or underscore and contain only letters, numbers, and underscores.

Example configuration using non-production placeholders:

```json
{
  "realm": "<account_id>",
  "consumer_key": "<consumer_key>",
  "consumer_secret": "<consumer_secret>",
  "token_key": "<token_id>",
  "token_secret": "<token_secret>",
  "queries": [
    {
      "name": "transactions",
      "query": "SELECT id, email, lastmodifieddate FROM transaction WHERE lastmodifieddate >= ? ORDER BY lastmodifieddate, id",
      "parameters": ["2024-01-01T00:00:00Z"],
      "primary_key": ["id"],
      "cursor_field": "lastmodifieddate",
      "cursor_parameter_index": 0
    },
    {
      "name": "transaction_totals",
      "query": "SELECT entity, SUM(total) AS total FROM transaction GROUP BY entity"
    }
  ],
  "page_size": 1000
}
```

Keep credentials in an untracked `.secrets/config.json` file. Do not commit
real account IDs, tokens, or consumer secrets.

## Sync Behavior

The connector sends each query as a `POST` request to
`/services/rest/query/v1/suiteql` with the required `Prefer: transient` header.
It returns the response `items` as records and follows NetSuite's `hasMore`,
`offset`, and `count` fields until all available pages have been read.

Discovery executes each configured query with `limit=1` and infers its stream
schema from the first row. An empty query result therefore produces a stream
with an open, empty object schema until a row is available on a later discovery.
NetSuite may normalize result field aliases to lowercase.

Queries without incremental settings support full refresh only. To enable
incremental sync with destination deduplication, configure all three of these
settings on the query:

| Field | Description |
| --- | --- |
| `primary_key` | One or more selected fields that uniquely identify each record. |
| `cursor_field` | A selected field with a consistently sortable value used for stream state. |
| `cursor_parameter_index` | The zero-based `parameters` position replaced with the saved cursor in incremental reads. |

The query must select both the primary-key and cursor fields, include a cursor
predicate with a bound parameter at the configured index, and use deterministic
ordering beginning with the cursor and ending with the primary key. Use an
inclusive predicate such as `lastmodifieddate >= ?`; records at the saved
cursor may be read again, and the primary key lets destinations deduplicate
them safely.

NetSuite REST SuiteQL returns at most 100,000 rows per query. Use
SuiteAnalytics Connect when a query must return more data.

## Local Development

Install the connector dependencies from this directory:

```bash
poetry install
```

Run the unit tests:

```bash
poetry run pytest unit_tests
```

Run the mocked integration tests:

```bash
poetry run pytest integration_tests
```

Run Airbyte commands with a local configuration:

```bash
poetry run source-netsuite-suiteql spec
poetry run source-netsuite-suiteql check --config .secrets/config.json
poetry run source-netsuite-suiteql discover --config .secrets/config.json
poetry run source-netsuite-suiteql read \
  --config .secrets/config.json \
  --catalog integration_tests/configured_catalog.json
```

## API References

- [Executing SuiteQL Queries Through REST Web Services](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_157909186990.html)
- [Collection Paging](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_156414087576.html)
- [SuiteQL Limitations and Exceptions](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_156257796125.html)
