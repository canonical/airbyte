# CaptivateIQ

This page contains the setup guide and reference information for the CaptivateIQ source connector.

## Prerequisites

**Required:**
- API Key

## Setup guide

### Step 1: Set up CaptivateIQ

Source CaptivateIQ is designed to interact with the data your permissions give you access to. To do so, you will need to use a CaptivateIQ API key.

## Step 2: Set up the CaptivateIQ connector in Airbyte

1. [Log into your Airbyte Cloud](https://cloud.airbyte.com/workspaces) account.
2. In the left navigation bar, click **Sources**. In the top-right corner, click **+new source**.
3. On the Set up the source page, enter the name for the CaptivateIQ connector and select **CaptivateIQ** from the Source type dropdown.
4. Enter your API key that you obtained from CaptivateIQ.
5. Click **Set up source**.

## Supported sync modes

The CaptivateIQ source connector supports the following [sync modes](https://docs.airbyte.com/cloud/core-concepts#connection-sync-modes):

- [Full Refresh - Overwrite](https://docs.airbyte.com/understanding-airbyte/connections/full-refresh-overwrite/)
- [Full Refresh - Append](https://docs.airbyte.com/understanding-airbyte/connections/full-refresh-append)
- [Full Refresh - Overwrite + Deduped](https://docs.airbyte.com/platform/using-airbyte/core-concepts/sync-modes/full-refresh-overwrite-deduped)

## Supported Streams

This connector outputs the following streams:

- Employees
- Audit Logs (Incremental)
- Attribute Worksheets
- Payouts
- Report Model
- Data Workbooks
- Data Worksheets
- Employee Assumptions
- Hierarchy Groups
- Transformation Worksheets
- Uploads
- Users
- Commission Plans
- Data Worksheet Records Export
- Transformation Worksheet Records Export

The two `*-records-export` streams use CaptivateIQ's asynchronous export endpoints. Exports are generated in full on every sync, so large workspaces can take a long time to sync these streams. Each record holds the exported row's columns in a `data` object. All values arrive as text.

`data-worksheet-records-export` and `transformation-worksheet-records-export` return every column of each worksheet, including derived and transformed columns, unlike `data-worksheet-records`, which only returns raw values. Each record also has `parent_id`, the worksheet ID. Join it to the `id` of the `data-worksheets-list` or `transformation-worksheets` stream to get the worksheet's name.

If there are more endpoints you'd like Airbyte to support, please [create an issue.](https://github.com/airbytehq/airbyte/issues/new/choose)

## Changelog

<details>
  <summary>Expand to review</summary>

| Version | Date       | Pull Request                                       | Subject                                              |
| :------ | :--------- | :------------------------------------------------- | :--------------------------------------------------- |
| 0.6.0   | 2026-11-24 | [#114](https://github.com/canonical/airbyte/pull/114) | Add export streams for data worksheet and transformation worksheet records |
| 0.1.0   | 2026-02-06 | [#47](https://github.com/airbytehq/airbyte/pull/#) | Initial release of CaptivateIQ connector for Airbyte |

</details>
