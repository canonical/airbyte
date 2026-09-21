# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

from source_expensify.base_stream import ExpensifyStream


REPORTS_EXPORT_TEMPLATE_PATH = "templates/reports_export_template.ftl"

# Expensify has no single "last updated" column, so the cursor is derived from these date
# columns (the most recent non-null value across them represents when the report last changed).
UPDATED_AT_SOURCE_FIELDS = ("created", "submitted", "approved", "reimbursed")
UPDATED_AT_CURSOR_FIELD = "updatedAt"

# The export filters only consider whichever of "created" or "submitted" occurred last.
EXPORT_FILTER_SOURCE_FIELDS = ("created", "submitted")
EXPORT_CURSOR_FIELD = "createdOrSubmittedAt"


class ExpensifyReports(ExpensifyStream):
    # Airbyte uses this to know what column uniquely identifies a row
    primary_key = "reportID"
    # Expensify has no native "updated at" column, so we derive one from the created/submitted/
    # approved/reimbursed date columns. Declaring it here is what enables the Incremental Append
    # and Incremental Append + Deduped sync modes.
    cursor_field = UPDATED_AT_CURSOR_FIELD
    cursor_source_fields = UPDATED_AT_SOURCE_FIELDS
    # Secondary, internal-only cursor (created/submitted only) used to resume/bound the export
    # window per Expensify's own startDate/endDate filter semantics.
    export_cursor_field = EXPORT_CURSOR_FIELD
    export_filter_source_fields = EXPORT_FILTER_SOURCE_FIELDS
    export_type = "combinedReportData"
    export_template_path = REPORTS_EXPORT_TEMPLATE_PATH
