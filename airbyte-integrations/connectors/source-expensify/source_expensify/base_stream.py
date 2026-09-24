# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""
Shared ingestion logic for Expensify streams (e.g. Reports, and the upcoming Expenses stream).

Every Expensify export follows the same three-step "trigger export -> download file -> parse CSV"
flow, the same retry/error-handling rules, and the same incremental resume/lookback semantics.
What differs *between* streams is:
  - the primary key
  - which date columns feed the cursor(s)
  - the FreeMarker template used to shape the export request
  - the resulting record schema

Concrete streams (see reports.py) subclass `ExpensifyStream` and only need to declare those
differences; all of the HTTP/export/parsing/state-management logic below is shared.
"""

import csv
import json
import pkgutil
import time
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Tuple

import requests

from airbyte_cdk.models import FailureType, SyncMode
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http.exceptions import DefaultBackoffException, UserDefinedBackoffException
from airbyte_cdk.sources.streams.http.rate_limiting import default_backoff_handler, user_defined_backoff_handler
from airbyte_cdk.utils.traced_exception import AirbyteTracedException


EXPENSIFY_URL = "https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations"
RAW_CSV_DEBUG_DIR = Path("/tmp/source_expensify_debug")

MAX_RETRIES = 5
RETRY_FACTOR = 5
RATE_LIMIT_BACKOFF_SECONDS = 10.0

# Lookback window for incremental syncs, reducing risk of missing report state transitions.
DEFAULT_LOOKBACK_WINDOW_DAYS = 30

# Formats observed in Expensify exports for date columns.
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


def _compute_max_date(row: Mapping[str, Any], fields: Tuple[str, ...]) -> Optional[str]:
    """Derive an ISO-8601 UTC value as the max of the given date columns on the row."""
    parsed_dates = []
    for field in fields:
        parsed_date = _parse_expensify_datetime(row.get(field))
        if parsed_date is not None:
            parsed_dates.append(parsed_date)

    if not parsed_dates:
        return None
    return max(parsed_dates).isoformat()


class ResourceNotFoundError(Exception):
    """Raised when the requested Expensify resource doesn't exist (HTTP 410). Expensify returns
    this generic "Gone" status for a variety of missing resources (e.g. policy, export file)."""


class CredentialsInvalidError(Exception):
    """Raised when the Expensify credentials are invalid (HTTP 401)."""


class RateLimitExceededError(Exception):
    """Raised when the Expensify API rate limit is exceeded (HTTP 429)."""


def _load_export_template(template_path: str) -> str:
    """Load an Expensify export template used to shape a stream's export CSV output."""
    package = __name__.split(".")[0]
    template_bytes = pkgutil.get_data(package, template_path)
    if template_bytes is None:
        raise FileNotFoundError(f"Unable to find {template_path} in the package.")
    return template_bytes.decode("utf-8")


def _map_response_code_to_exception(response_code: int) -> None:
    """Map an Expensify response code to an exception."""
    if response_code == requests.codes.gone:
        # Expensify returns 410 for a variety of missing resources.
        raise ResourceNotFoundError(f"Expensify resource not found.")
    elif response_code == requests.codes.unauthorized:
        # Expensify returns 401 if the credentials are invalid
        raise CredentialsInvalidError(f"Expensify credentials are invalid.")
    elif response_code == requests.codes.too_many_requests:
        # Expensify returns 429 if the API rate limit is exceeded
        raise RateLimitExceededError(f"Expensify API rate limit exceeded.")
    elif response_code >= 500:
        # 5xx codes indicate a problem on Expensify's side that may be transient.
        raise AirbyteTracedException(
            internal_message=f"Expensify returned server error response code {response_code}.",
            message=f"Expensify API request failed with a server error (code {response_code}). This is likely transient, please try again later.",
            failure_type=FailureType.transient_error,
        )
    elif response_code >= requests.codes.bad_request:
        # Other 4xx codes typically won't succeed on retry, so surface them to Airbyte as a config error.
        raise AirbyteTracedException(
            internal_message=f"Expensify returned client error response code {response_code}.",
            message=f"Expensify API request failed with client error (code {response_code}). Please verify your configuration.",
            failure_type=FailureType.config_error,
        )


@user_defined_backoff_handler(max_tries=MAX_RETRIES)
@default_backoff_handler(max_tries=MAX_RETRIES, factor=RETRY_FACTOR)
def _send_request(payload: Mapping[str, Any]) -> requests.Response:
    """
    Send the actual HTTP request to the Expensify Integration Server, retrying it using the
    Airbyte CDK's standard backoff handlers: HTTP 429 responses back off for a fixed duration,
    transient 5xx/connection errors are retried with exponential backoff, and all other 4xx
    errors are treated as permanent failures and raised immediately without retrying.
    """
    response = requests.post(EXPENSIFY_URL, data=payload, timeout=60)
    if response.status_code == requests.codes.too_many_requests:
        raise UserDefinedBackoffException(backoff=RATE_LIMIT_BACKOFF_SECONDS, request=response.request, response=response)
    if response.status_code >= 500:
        raise DefaultBackoffException(request=response.request, response=response)
    if response.status_code >= requests.codes.bad_request:
        # Route real HTTP-level 4xx errors (e.g. an actual HTTP 410/401 response) through the
        # same classification as Expensify's "200 OK with JSON error body" quirk.
        _map_response_code_to_exception(response.status_code)
    return response


def _post_job_description(job_description: Mapping[str, Any], template: Optional[str] = None) -> requests.Response:
    """
    Send a requestJobDescription to the Expensify Integration Server.

    Expensify requires the `requestJobDescription` form field to be a JSON-encoded string.

    `template` (when provided) must be sent as its own top-level form field, sibling to
    `requestJobDescription`.
    """
    payload = {"requestJobDescription": json.dumps(job_description)}
    if template is not None:
        payload["template"] = template
    response = _send_request(payload)

    # Expensify returns HTTP 200 even for some error conditions, with a JSON error body
    # like {"responseMessage": "...", "responseCode": 500}. Detect and surface those.
    stripped = response.text.strip()
    if stripped.startswith("{") and '"responseCode"' in stripped:
        try:
            error_body = json.loads(stripped)
        except json.JSONDecodeError:
            error_body = None
        if error_body and "responseCode" in error_body:
            response_code = error_body.get("responseCode")
            _map_response_code_to_exception(response_code)

    return response


class ExpensifyStream(Stream):
    """
    Base class for Expensify export-backed streams.

    Subclasses must declare:
      - `primary_key`: the column(s) that uniquely identify a row.
      - `cursor_field` / `cursor_source_fields`: the public cursor field name and the date
        columns whose max value populates it (Expensify has no native "updated at" column).
      - `export_cursor_field` / `export_filter_source_fields`: an internal-only cursor, tracked
        alongside `cursor_field`, used to resume/bound the export window per Expensify's own
        startDate/endDate filter semantics (which may consider a narrower set of date columns).
      - `export_type`: the Expensify `inputSettings.type` value for this export.
      - `export_template_path`: the package-relative path to the FreeMarker template used to
        shape this stream's export CSV output.
    """

    primary_key: Any = None
    cursor_field: str = ""
    cursor_source_fields: Tuple[str, ...] = ()
    export_cursor_field: str = ""
    export_filter_source_fields: Tuple[str, ...] = ()
    export_type: str = ""
    export_template_path: str = ""

    def __init__(
        self,
        name: str,
        partner_user_id: str,
        partner_user_secret: str,
        start_date: str,
        end_date: Optional[str] = None,
        report_state: Optional[List[str]] = None,
        lookback_window_days: int = DEFAULT_LOOKBACK_WINDOW_DAYS,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._name = name
        self.partner_user_id = partner_user_id
        self.partner_user_secret = partner_user_secret
        self.start_date = start_date
        # No end_date means no upper bound: export up to the current date.
        self.end_date = end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # No report_state means no filter: Expensify includes reports in all states.
        self.report_state = ",".join(report_state) if report_state else None
        self.lookback_window_days = lookback_window_days

    @property
    def name(self) -> str:
        return self._name

    def _compute_cursor(self, row: Mapping[str, Any]) -> Optional[str]:
        """Derive an ISO-8601 UTC cursor value as the max of `cursor_source_fields` on the row."""
        return _compute_max_date(row, self.cursor_source_fields)

    def _compute_export_cursor(self, row: Mapping[str, Any]) -> Optional[str]:
        """
        Derive the value used to track export window progress, matching Expensify's own
        startDate/endDate filter semantics (max of `export_filter_source_fields` only).
        """
        return _compute_max_date(row, self.export_filter_source_fields)

    def get_updated_state(self, current_stream_state: Mapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        current_stream_state = current_stream_state or {}
        new_state = dict(current_stream_state)

        # `cursor_field` drives dedup.
        cursor_candidates = [
            value for value in (current_stream_state.get(self.cursor_field), latest_record.get(self.cursor_field)) if value
        ]
        if cursor_candidates:
            new_state[self.cursor_field] = max(cursor_candidates)

        # `export_cursor_field` drives the export window.
        export_cursor_candidates = [
            value for value in (current_stream_state.get(self.export_cursor_field), latest_record.get(self.export_cursor_field)) if value
        ]
        if export_cursor_candidates:
            new_state[self.export_cursor_field] = max(export_cursor_candidates)

        return new_state

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        self.logger.info(f"Reading records from Expensify for {self.name}")

        export_start_date = self._parse_state(stream_state, sync_mode)

        if export_start_date > self.end_date:
            self.logger.info(
                f"Skipping export: resumed cursor date {export_start_date} is past the configured "
                f"end_date {self.end_date}. All data in the configured date range has already been synced."
            )
            return

        export_chunks = self._generate_export_chunks(export_start_date, self.end_date)
        self.logger.info(
            f"Splitting Expensify export for {self.name} into {len(export_chunks)} chunk(s) of at most one "
            f"calendar month each, covering startDate={export_start_date} to endDate={self.end_date}."
        )

        record_count = 0
        for chunk_start_date, chunk_end_date in export_chunks:
            self.logger.info(
                f"Requesting Expensify export chunk for {self.name} with filters: "
                f"startDate={chunk_start_date}, endDate={chunk_end_date}, "
                f"reportState={self.report_state or 'all'}."
            )

            csv_data = self._retrieve_csv(chunk_start_date, chunk_end_date)

            # Parse CSV in memory and yield rows to Airbyte
            reader = csv.DictReader(StringIO(csv_data))
            for row in reader:
                # Airbyte takes these yielded dicts, validates them against the schema,
                # and streams them to the destination connector.
                row[self.cursor_field] = self._compute_cursor(row)
                row[self.export_cursor_field] = self._compute_export_cursor(row)
                record_count += 1
                yield row
        self.logger.info(f"Parsed {record_count} record(s) from Expensify export.")

    @staticmethod
    def _generate_export_chunks(start_date: str, end_date: str) -> List[Tuple[str, str]]:
        """
        Split [start_date, end_date] into calendar-month-aligned chunks, so that each individual
        Expensify export request covers at most one month of data. This bounds the size of any
        single downloaded CSV file and of the data held in memory at once, regardless of how wide
        the overall configured (or resumed) export window is.

        The first chunk runs from `start_date` through the last day of that month; any full
        months in between form their own chunk; the final chunk runs from the first day of its
        month through `end_date`.
        """
        chunk_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        chunks: List[Tuple[str, str]] = []
        while chunk_start <= end:
            last_day_of_month = monthrange(chunk_start.year, chunk_start.month)[1]
            month_end = chunk_start.replace(day=last_day_of_month)
            chunk_end = min(month_end, end)
            chunks.append((chunk_start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
            chunk_start = chunk_end + timedelta(days=1)

        return chunks

    def _parse_state(self, stream_state: Mapping[str, Any], sync_mode: SyncMode = SyncMode.full_refresh) -> str:
        """
        Parse the stream state to determine the start date for the export window.

        For incremental syncs, resume the export window from the last synced cursor value
        instead of re-exporting (and re-scanning) the full configured date range every time.
        """
        stream_state = stream_state or {}
        state_export_cursor_value = stream_state.get(self.export_cursor_field) if sync_mode == SyncMode.incremental else None
        export_start_date = self.start_date
        if state_export_cursor_value:
            # Expensify's export filter is date-only (YYYY-MM-DD)
            state_cursor_date = state_export_cursor_value[:10]
            # Trail the resumed cursor back by `lookback_window_days`.
            lookback_date = (datetime.strptime(state_cursor_date, "%Y-%m-%d") - timedelta(days=self.lookback_window_days)).strftime(
                "%Y-%m-%d"
            )
            export_start_date = max(self.start_date, lookback_date)

        return export_start_date

    def _retrieve_csv(self, export_start_date: str, export_end_date: str) -> str:
        """
        Triggers an Expensify export and downloads the resulting CSV.

        Params:
            export_start_date: The start date for the export window (chunk).
            export_end_date: The end date for the export window (chunk).

        Returns:
            The CSV data as a string.

        Raises:
            ResourceNotFoundError: if the exported file itself is not yet or no longer available.
            CredentialsInvalidError: if the Expensify credentials are invalid.
        """
        try:
            # Trigger the Export Job
            file_name = self._trigger_export(start_date=export_start_date, end_date=export_end_date)
        except ResourceNotFoundError as e:
            raise AirbyteTracedException(
                internal_message=str(e),
                message=(f"Expensify returned 'resource not found' (HTTP 410) while triggering the {self.name} export. "),
                failure_type=FailureType.config_error,
            ) from e
        except CredentialsInvalidError as e:
            raise AirbyteTracedException(
                internal_message=str(e),
                message=(
                    f"Expensify credentials are invalid (HTTP 401) while triggering the {self.name} export. "
                    "Please verify your Partner User ID and Partner User Secret."
                ),
                failure_type=FailureType.config_error,
            ) from e
        self.logger.info(f"Triggered Expensify export for file {file_name}.")

        try:
            # Download the CSV
            csv_data = self._download_file(file_name)
        except ResourceNotFoundError as e:
            # A 410 here means the exported file itself is not yet or no longer available.
            raise AirbyteTracedException(
                internal_message=str(e),
                message=(f"Expensify returned 'resource not found' (HTTP 410) while downloading the exported file '{file_name}'. "),
                failure_type=FailureType.config_error,
            ) from e
        self.logger.info(f"Downloaded Expensify export ({len(csv_data)} bytes) for file {file_name}.")

        return csv_data

    def _trigger_export(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
        input_settings = {
            "type": self.export_type,
            "filters": {
                "startDate": start_date if start_date is not None else self.start_date,
                "endDate": end_date if end_date is not None else self.end_date,
            },
        }
        # Omitting "reportState" entirely means Expensify includes reports in all states.
        if self.report_state:
            input_settings["reportState"] = self.report_state
        job_description = {
            "type": "file",
            "credentials": {
                "partnerUserID": self.partner_user_id,
                "partnerUserSecret": self.partner_user_secret,
            },
            "onReceive": {"immediateResponse": ["returnRandomFileName"]},
            "inputSettings": input_settings,
            "outputSettings": {"fileExtension": "csv"},
        }
        response = _post_job_description(job_description, template=_load_export_template(self.export_template_path))
        return response.text.strip()

    def _download_file(self, file_name: str) -> str:
        job_description = {
            "type": "download",
            "credentials": {"partnerUserID": self.partner_user_id, "partnerUserSecret": self.partner_user_secret},
            "fileName": file_name,
            "fileSystem": "integrationServer",
        }
        response = _post_job_description(job_description)
        return response.text
