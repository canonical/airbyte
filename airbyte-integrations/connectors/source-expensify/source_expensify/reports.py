# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import pkgutil
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from source_expensify.base_stream import ExpensifyExportStream


REPORTS_EXPORT_TEMPLATE_PATH = "templates/reports_export_template.ftl"

# Expensify has no single "last updated" column, so the cursor is derived from these date
# columns (the most recent non-null value across them represents when the report last changed).
UPDATED_AT_SOURCE_FIELDS = ("created", "submitted", "approved", "reimbursed")
UPDATED_AT_CURSOR_FIELD = "updatedAt"
# Formats observed in Expensify report exports for the date columns above.
_EXPENSIFY_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _parse_expensify_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an Expensify date column into an aware UTC datetime, or None if empty/unparseable."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    for fmt in _EXPENSIFY_DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _compute_updated_at(row: Mapping[str, Any]) -> Optional[str]:
    """Derive an ISO-8601 UTC 'updatedAt' cursor value as the max of the report's date columns."""
    parsed_dates = []
    for field in UPDATED_AT_SOURCE_FIELDS:
        parsed_date = _parse_expensify_datetime(row.get(field))
        if parsed_date is not None:
            parsed_dates.append(parsed_date)

    if not parsed_dates:
        return None
    return max(parsed_dates).isoformat()


def _load_reports_export_template() -> str:
    """Load the Expensify export template used to shape the combined report CSV output."""
    package = __name__.split(".")[0]
    template_bytes = pkgutil.get_data(package, REPORTS_EXPORT_TEMPLATE_PATH)
    if template_bytes is None:
        raise FileNotFoundError(f"Unable to find {REPORTS_EXPORT_TEMPLATE_PATH} in the package.")
    return template_bytes.decode("utf-8")


class ExpensifyReports(ExpensifyExportStream):
    # Airbyte uses this to know what column uniquely identifies a row
    primary_key = "reportID"
    # Expensify has no native "updated at" column, so we derive one (see _compute_updated_at)
    # from the created/submitted/approved/reimbursed date columns. Declaring it here is what
    # enables the Incremental Append and Incremental Append + Deduped sync modes.
    cursor_field = UPDATED_AT_CURSOR_FIELD

    def _input_settings(self, start_date: Optional[str]) -> Mapping[str, Any]:
        return {
            "type": "combinedReportData",
            "filters": {
                "startDate": start_date if start_date is not None else self.start_date,
                "endDate": self.end_date,
            },
            "reportState": "REIMBURSED",
        }

    def _export_template(self) -> Optional[str]:
        return _load_reports_export_template()

    def _compute_cursor_value(self, row: Mapping[str, Any]) -> Optional[str]:
        return _compute_updated_at(row)
