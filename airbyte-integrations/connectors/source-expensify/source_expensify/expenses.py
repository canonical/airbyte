# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

from source_expensify.base_stream import ExpensifyStream


EXPENSES_EXPORT_TEMPLATE_PATH = "templates/expenses_export_template.ftl"

# Expensify has no single "last updated" column for a transaction, so the cursor is derived from
# these date columns (the most recent non-null value across them represents when the expense
# last changed).
UPDATED_AT_SOURCE_FIELDS = ("created", "modifiedCreated", "inserted")
UPDATED_AT_CURSOR_FIELD = "updatedAt"

# The export filters only consider the (report-level) "created" date, since this template flattens
# each report's transactions and does not surface a report-level "submitted" column.
EXPORT_FILTER_SOURCE_FIELDS = ("created",)
EXPORT_CURSOR_FIELD = "createdAt"


class ExpensifyExpenses(ExpensifyStream):
    # Airbyte uses this to know what column uniquely identifies a row
    primary_key = "transactionID"
    # Expensify has no native "updated at" column, so we derive one from the created/
    # modifiedCreated/inserted date columns. Declaring it here is what enables the Incremental
    # Append and Incremental Append + Deduped sync modes.
    cursor_field = UPDATED_AT_CURSOR_FIELD
    cursor_source_fields = UPDATED_AT_SOURCE_FIELDS
    # Secondary, internal-only cursor (created only) used to resume/bound the export window per
    # Expensify's own startDate/endDate filter semantics.
    export_cursor_field = EXPORT_CURSOR_FIELD
    export_filter_source_fields = EXPORT_FILTER_SOURCE_FIELDS
    # Expenses are sourced from the same combinedReportData export as Reports; only the template
    # differs, flattening each report's transactionList into one row per expense.
    export_type = "combinedReportData"
    export_template_path = EXPENSES_EXPORT_TEMPLATE_PATH
