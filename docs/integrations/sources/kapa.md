# Kapa

This page contains setup and reference information for the Kapa source connector. The connector reads project threads, end users, integrations, knowledge sources, source groups, aggregate activity, Top Questions, and Coverage Gaps from the Kapa Query and Ingestion APIs.

## Prerequisites

- A Kapa API key with access to the project
- The Kapa project UUID
- An ISO 8601 start date for the earliest thread and aggregate activity to sync

## Setup Guide

### Step 1: Prepare Kapa Access

Obtain an API key and the UUID of the Kapa project you want to sync. The connector sends the key in the `X-API-KEY` header. Keep it in a secret manager and do not place it in source control.

See the [Kapa Analytics API overview](https://docs.kapa.ai/analytics/analytics-api), [List Threads API reference](https://docs.kapa.ai/api/reference/query-v-1-projects-threads-list), [List End Users API reference](https://docs.kapa.ai/api/reference/query-v-1-projects-end-users-list), [List Integrations API reference](https://docs.kapa.ai/api/reference/query-v-1-projects-integrations-list), and [Sources API reference](https://docs.kapa.ai/api/reference/sources) for the endpoint contracts.

### Step 2: Set Up the Kapa Source in Airbyte

1. In Airbyte, select **Sources**, then select **New source**.
2. Choose **Kapa** as the source type.
3. Enter a name for the source.
4. Enter the Kapa API key.
5. Enter the project UUID.
6. Enter the start date in ISO 8601 format, for example `2026-08-27T00:00:00Z`.
7. Select an analytics interval: weekly, monthly, or quarterly. The default is monthly.
8. Select **Set up source**.

## Supported Sync Modes

The Kapa source supports:

- Full Refresh - Overwrite
- Full Refresh - Append
- Incremental - Append
- Incremental - Append + Deduped

Incremental append-dedup is recommended for `threads` and `activity`. Threads use `id` as the primary key and `last_activity_at` as the cursor. Activity uses `activity_date` as both its primary key and cursor. All other streams support full refresh only.

## Supported Streams

| Stream                   | Description                                                                             | Primary Key       | Cursor             | Pagination                                                          |
| ------------------------ | --------------------------------------------------------------------------------------- | ----------------- | ------------------ | ------------------------------------------------------------------- |
| `threads`                | Project threads, question-answer pairs, and requested nested metadata                   | `id`              | `last_activity_at` | Signed cursor, up to 500 records per page                           |
| `activity`               | Daily aggregate query, feedback, user, deflection, language, and integration statistics | `activity_date`   | `activity_date`    | One UTC date window per request                                     |
| `top_questions_periods`  | Completed Top Questions periods for the configured interval                             | `id`              | None               | Signed cursor, up to 500 records per page                           |
| `top_questions_clusters` | Frequently asked question clusters for each Top Questions period                        | `period_id`, `id` | None               | One signed-cursor traversal per period, up to 500 clusters per page |
| `coverage_gaps_periods`  | Completed Coverage Gaps periods for the configured interval                             | `id`              | None               | Signed cursor, up to 500 records per page                           |
| `coverage_gaps_clusters` | Uncertain-answer clusters and documentation suggestions for each Coverage Gaps period   | `period_id`, `id` | None               | One signed-cursor traversal per period, up to 500 clusters per page |
| `end_users`              | Tracked users, identity fields, activity bounds, and latest thread context              | `id`              | None               | Numbered pages from the API-provided `next` URL                     |
| `integrations`           | Deployment integrations configured for the project                                      | `id`              | None               | None; the endpoint returns a direct array                           |
| `source_groups`          | Project source groups, including nested product and version groups                      | `id`              | None               | Numbered pages from the API-provided `next` URL                     |
| `sources`                | Knowledge sources and their source-group membership                                     | `id`              | None               | Numbered pages from the API-provided `next` URL                     |

## Incremental Behavior

For threads, the connector sends the saved cursor through Kapa's inclusive `updated_since` filter and requests records in ascending `last_activity_at` order. Because the lower bound is inclusive, the record at a state boundary can appear in two consecutive syncs. Append-dedup removes that duplicate using the stable thread `id`.

For activity, Airbyte creates one UTC window per day and uses `activity_date` as both the cursor and append-dedup key. Every sync reloads the previous and current UTC day. This updates delayed totals for yesterday and refreshes today's partial aggregate before the next day begins.

## Analytics Behavior

`activity` emits one nested record per UTC day. Completed days cover midnight through `23:59:59`; the current day covers midnight through the sync time and has `is_complete: false`. Records include `window_start`, `window_end`, aggregate statistics, and statistics by integration.

Top Questions and Coverage Gaps are organized as parent periods and child clusters. The connector first lists completed periods for the selected interval, then retrieves every page of clusters for each period. Cluster records include `period_id` and `analytics_interval` so downstream models can retain that context.

Kapa includes at most 100 recent thread summaries in each cluster. `thread_count` reports the true total and can exceed the length of the `threads` array. Coverage Gaps clusters additionally include a documentation `suggestion`.

## End-User Data

The `end_users` stream performs a full refresh because Kapa does not expose an incremental filter or cursor for this endpoint. Depending on how user tracking is configured, records can include email addresses, company names, client identifiers, identity-provider subject IDs, and the latest user-authored question. Restrict destination access and apply retention policies appropriate for personal data.

## Project Resources

The `integrations`, `source_groups`, and `sources` streams perform full refreshes because their endpoints do not expose incremental filters or cursors. Integrations describe where a Kapa project is deployed. Source groups organize knowledge by product or version, and sources describe the configured knowledge inputs and their group membership.

## Rate Limits and Retries

Kapa does not publish endpoint-specific limits for these endpoints. The connector honors `Retry-After` on HTTP 429 responses and uses bounded fallback retries for rate-limit-related 403 responses and transient 502, 503, and 504 responses. Permission-related 403 responses fail without retrying.

## IP Allow List

If your organization restricts access to specific IPs, add the [Airbyte Cloud IP addresses](https://docs.airbyte.com/platform/operating-airbyte/ip-allowlist) to your allow list.

## Changelog

<details>
  <summary>Expand to review</summary>

| Version | Date       | Pull Request | Subject                                                        |
| ------- | ---------- | ------------ | -------------------------------------------------------------- |
| 0.1.0   | 2026-09-03 |              | Initial release with threads, end users, and analytics streams |

</details>
