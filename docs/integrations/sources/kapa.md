# Kapa

This page contains setup and reference information for the Kapa source connector. The connector reads project threads, aggregate activity, Top Questions, and Coverage Gaps from the Kapa Query API v1.

## Prerequisites

- A Kapa API key with access to the project
- The Kapa project UUID
- An ISO 8601 start date for the earliest thread and aggregate activity to sync

## Setup Guide

### Step 1: Prepare Kapa Access

Obtain an API key and the UUID of the Kapa project you want to sync. The connector sends the key in the `X-API-KEY` header. Keep it in a secret manager and do not place it in source control.

See the [Kapa Analytics API overview](https://docs.kapa.ai/analytics/analytics-api) and [List Threads API reference](https://docs.kapa.ai/api/reference/query-v-1-projects-threads-list) for the endpoint contracts.

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

Incremental append-dedup is recommended for `threads`, which uses `id` as the primary key and `last_activity_at` as the cursor. Analytics streams support full refresh only.

## Supported Streams

| Stream                   | Description                                                                           | Primary Key       | Cursor             | Pagination                                                          |
| ------------------------ | ------------------------------------------------------------------------------------- | ----------------- | ------------------ | ------------------------------------------------------------------- |
| `threads`                | Project threads, question-answer pairs, and requested nested metadata                 | `id`              | `last_activity_at` | Signed cursor, up to 500 records per page                           |
| `activity`               | Aggregate query, feedback, user, deflection, language, and per-integration statistics | None              | None               | None                                                                |
| `top_questions_periods`  | Completed Top Questions periods for the configured interval                           | `id`              | None               | Signed cursor, up to 500 records per page                           |
| `top_questions_clusters` | Frequently asked question clusters for each Top Questions period                      | `period_id`, `id` | None               | One signed-cursor traversal per period, up to 500 clusters per page |
| `coverage_gaps_periods`  | Completed Coverage Gaps periods for the configured interval                           | `id`              | None               | Signed cursor, up to 500 records per page                           |
| `coverage_gaps_clusters` | Uncertain-answer clusters and documentation suggestions for each Coverage Gaps period | `period_id`, `id` | None               | One signed-cursor traversal per period, up to 500 clusters per page |

## Incremental Behavior

The connector sends the saved cursor through Kapa's inclusive `updated_since` filter and requests records in ascending `last_activity_at` order. Because the lower bound is inclusive, the record at a state boundary can appear in two consecutive syncs. Append-dedup removes that duplicate using the stable thread `id`.

## Analytics Behavior

`activity` emits one nested record for the range from the configured start date through the sync start time. It contains aggregate statistics and a list of statistics by integration.

Top Questions and Coverage Gaps are organized as parent periods and child clusters. The connector first lists completed periods for the selected interval, then retrieves every page of clusters for each period. Cluster records include `period_id` and `analytics_interval` so downstream models can retain that context.

Kapa includes at most 100 recent thread summaries in each cluster. `thread_count` reports the true total and can exceed the length of the `threads` array. Coverage Gaps clusters additionally include a documentation `suggestion`.

## Rate Limits and Retries

Kapa does not publish endpoint-specific limits for these endpoints. The connector honors `Retry-After` on HTTP 429 responses and uses bounded fallback retries for rate-limit-related 403 responses and transient 502, 503, and 504 responses. Permission-related 403 responses fail without retrying.

## IP Allow List

If your organization restricts access to specific IPs, add the [Airbyte Cloud IP addresses](https://docs.airbyte.com/platform/operating-airbyte/ip-allowlist) to your allow list.

## Changelog

<details>
  <summary>Expand to review</summary>

| Version | Date       | Pull Request | Subject                                            |
| ------- | ---------- | ------------ | -------------------------------------------------- |
| 0.1.0   | 2026-09-03 |              | Initial release with threads and analytics streams |

</details>
