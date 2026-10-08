# NetSuite SuiteQL Source

This connector replicates configured NetSuite tables through SuiteQL REST web
services. It generates the SuiteQL itself so configurations cannot project,
aggregate, alias, or otherwise transform source data.

This is separate from `source-netsuite`, which discovers and reads NetSuite
objects through the Record API. SuiteQL has a different endpoint, response
shape, schema-discovery strategy, and configuration workflow.

## Supports: 

- NetSuite token-based OAuth 1 authentication with HMAC-SHA256
- Multiple tables in one source configuration
- Connector-generated `SELECT *` queries
- Offset pagination with a configurable page size
- Runtime JSON schema inference from up to the first 100 returned rows
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
| `tables` | Yes | One or more table definitions containing `table_name` and an optional `schema_override`. |
| `page_size` | No | Rows requested per page, from 1 to 1000. Defaults to 1000. |

Table names must start with a letter or underscore and contain only letters,
numbers, and underscores. They must be unique and are also used as Airbyte
stream names.

Example configuration using non-production placeholders:

```json
{
  "realm": "<account_id>",
  "consumer_key": "<consumer_key>",
  "consumer_secret": "<consumer_secret>",
  "token_key": "<token_id>",
  "token_secret": "<token_secret>",
  "tables": [
    {
      "table_name": "transactionLine",
      "schema_override": [
        {"field_name": "custcol_ns_can_contract", "field_type": "string"},
        {"field_name": "netamount", "field_type": "number"},
        {"field_name": "custcol_can_percent_complete", "field_type": "number"},
        {"field_name": "item", "field_type": "string"},
        {"field_name": "custcol_ns_can_oli", "field_type": "string"},
        {"field_name": "cseg_lobs", "field_type": "string"},
        {"field_name": "cseg_revenue_family", "field_type": "string"}
      ]
    }
  ],
  "page_size": 1000
}
```

Keep credentials in an untracked `.secrets/config.json` file. Do not commit
real account IDs, tokens, or consumer secrets.

## Sync Behavior

The connector sends each generated query as a `POST` request to
`/services/rest/query/v1/suiteql` with the required `Prefer: transient` header.
It returns the response `items` as records and follows NetSuite's `hasMore`,
`offset`, and `count` fields until all available pages have been read.

Discovery runs `SELECT *` for each configured table and infers its stream schema
from a sample of returned rows. An empty result therefore produces a stream with
an open, empty object schema until a row is available on a later discovery.
NetSuite may also omit fields whose values are null. Add known fields to the
table's `schema_override` list when they must be present in the discovered schema.
The override is appended to sampled fields: it does not remove inferred fields,
and conflicting configured and observed types are combined. Supported configured
types are `string`, `number`, `integer`, `boolean`, `object`, and `array`.
NetSuite may normalize field names to lowercase.

Every table supports full refresh and incremental sync. Configure the primary
key and cursor after discovery in the Airbyte connection catalog:

1. Select the stream and choose **Incremental | Append + Deduped** as its sync mode.
2. Select one or more top-level primary-key fields for deduplication.
3. Select one top-level date or timestamp cursor field.

The connector owns the query shape. For `transaction`, `id`, and
`lastmodifieddate` selected in the catalog, it generates the equivalent of:

```sql
SELECT
  *,
  TO_CHAR(lastmodifieddate, 'YYYY-MM-DD HH24:MI:SS') AS cursor_ts
FROM transaction
WHERE lastmodifieddate >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
ORDER BY cursor_ts, id
```

The connector uses the fixed-width `cursor_ts` alias internally, then writes the
normalized value back to the selected cursor field for Airbyte state. Incremental
reads add the matching inclusive predicate `lastmodifieddate >= TO_DATE(?,
'YYYY-MM-DD HH24:MI:SS')`; boundary records may be read again and are safely
deduplicated by the selected primary key.

NetSuite REST SuiteQL returns at most 100,000 rows per query. Use
SuiteAnalytics Connect when a query must return more data.

## Local Development

Install dependencies and list the available workflow targets:

```bash
make install
make help
```

Run the standard local validation sequence:

```bash
make unit-test
make integration-test
make connector-test
make build
make spec
```

Create an untracked `.secrets/config.json` containing real NetSuite credentials
before running live protocol commands. These commands use `CONFIG`, `CATALOG`,
and `STATE` Make variables, which can be overridden for another test fixture.

```bash
make check
make discover
make read
```

## Local Airbyte UI

Build the local development image and start an Airbyte instance:

```bash
make build
abctl local install
```

In **Workspace settings** > **Sources**, choose **New connector** > **Add a new
Docker connector**. Set the image name to `airbyte/source-netsuite-suiteql` and
the tag to `dev`. Ensure the Airbyte deployment can access that image. You can
then create a source with table names and optional schema overrides, refresh the
schema, and choose the primary key and cursor in the connection catalog.

Make the rebuilt image available to the deployment after each `make build`
before starting another sync.

Run the Airbyte CI acceptance workflow after preparing its Poetry environment:

```bash
cd ../../../airbyte-ci/connectors/pipelines
poetry install
cd ../../../airbyte-integrations/connectors/source-netsuite-suiteql
make test
```

The committed acceptance configuration validates the connector specification
without credentials. Live acceptance checks require a local
`.secrets/config.json` with permission to query the configured tables.

## API References

- [Executing SuiteQL Queries Through REST Web Services](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_157909186990.html)
- [Collection Paging](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_156414087576.html)
- [SuiteQL Limitations and Exceptions](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_156257796125.html)
