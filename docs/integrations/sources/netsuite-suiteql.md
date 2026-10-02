# NetSuite SuiteQL

The NetSuite SuiteQL source runs user-defined SuiteQL queries through NetSuite
REST Web Services. Every named query in the source configuration is exposed as
an Airbyte stream. This connector is distinct from the NetSuite source, which
reads Record API objects rather than SuiteQL query results.

## Prerequisites

- A NetSuite account with REST Web Services enabled
- A token-based authentication integration and access token
- A NetSuite role permitted to execute each configured SuiteQL query

## Setup Guide

### Step 1: Enable NetSuite Access

Enable REST Web Services and token-based authentication in NetSuite. Create an
integration, assign a role with access to the records queried, and create an
access token for that integration and role. Store the resulting consumer and
token credentials in a secret manager.

See NetSuite's [authentication documentation](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_4389727047.html) and [SuiteQL REST API documentation](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_157909186990.html).

### Step 2: Set Up the Source in Airbyte

1. In Airbyte, select **Sources**, then select **New source**.
2. Choose **NetSuite SuiteQL**.
3. Enter a source name.
4. Enter the NetSuite realm, consumer key and secret, and token ID and secret.
5. Add one or more named SuiteQL queries.
6. Optionally set a page size from 1 through 1000.
7. Select **Set up source**.

Each query name must begin with a letter or underscore and contain only
letters, numbers, and underscores.

## Supported Sync Modes

All SuiteQL query streams support Full Refresh. A query supports Incremental
Append + Deduped when it defines `primary_key`, `cursor_field`, and
`cursor_parameter_index` together.

The query must select its primary-key and cursor fields, use a cursor predicate
with the configured bound parameter, and order records deterministically by the
cursor followed by the primary key. Inclusive cursor predicates can emit the
state-boundary row again; destination deduplication removes that duplicate.

## Supported Streams

Streams are defined by the `queries` array in source configuration. Each query
creates one stream using its `name`; its schema is inferred during discovery
from the first returned row. Empty query results produce an open object schema
until a later discovery sees a row.

## Pagination and Limits

The connector sends query requests to NetSuite's SuiteQL REST endpoint and
follows the `hasMore`, `offset`, and `count` response fields. NetSuite returns
at most 100,000 rows per SuiteQL query. Narrow high-volume queries or use
SuiteAnalytics Connect when more rows are required.

## IP Allow List

If your organization restricts access by IP address, add the [Airbyte Cloud IP
addresses](https://docs.airbyte.com/platform/operating-airbyte/ip-allowlist) to
the allow list.
