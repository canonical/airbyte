# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import csv
import json
import pkgutil
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Tuple

import requests

from airbyte_cdk.models import FailureType, SyncMode
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http.exceptions import DefaultBackoffException, UserDefinedBackoffException
from airbyte_cdk.sources.streams.http.rate_limiting import default_backoff_handler, user_defined_backoff_handler
from airbyte_cdk.utils.traced_exception import AirbyteTracedException


EXPENSIFY_URL = "https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations"
RAW_CSV_DEBUG_DIR = Path("/tmp/source_expensify_debug")
REPORTS_EXPORT_TEMPLATE_PATH = "templates/reports_export_template.ftl"

MAX_RETRIES = 5
RETRY_FACTOR = 5
RATE_LIMIT_BACKOFF_SECONDS = 10.0

# Expensify has no single "last updated" column, so the cursor is derived from these date
# columns (the most recent non-null value across them represents when the report last changed).
UPDATED_AT_SOURCE_FIELDS = ("created", "submitted", "approved", "reimbursed")
UPDATED_AT_CURSOR_FIELD = "updatedAt"

# The export filters only consider whichever of "created" or "submitted" occurred last.
EXPORT_FILTER_SOURCE_FIELDS = ("created", "submitted")
EXPORT_CURSOR_FIELD = "createdOrSubmittedAt"

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


def _compute_updated_at(row: Mapping[str, Any]) -> Optional[str]:
    """Derive an ISO-8601 UTC 'updatedAt' cursor value as the max of the report's date columns."""
    return _compute_max_date(row, UPDATED_AT_SOURCE_FIELDS)


def _compute_export_cursor(row: Mapping[str, Any]) -> Optional[str]:
    """
    Derive the value used to track export window progress, matching Expensify's own
    startDate/endDate filter semantics (max of "created"/"submitted" only).
    """
    return _compute_max_date(row, EXPORT_FILTER_SOURCE_FIELDS)


class ResourceNotFoundError(Exception):
    """Raised when the requested Expensify resource doesn't exist (HTTP 410). Expensify returns
    this generic "Gone" status for a variety of missing resources (e.g. policy, export file)."""


class CredentialsInvalidError(Exception):
    """Raised when the Expensify credentials are invalid (HTTP 401)."""


class RateLimitExceededError(Exception):
    """Raised when the Expensify API rate limit is exceeded (HTTP 429)."""


def _load_reports_export_template() -> str:
    """Load the Expensify export template used to shape the combined report CSV output."""
    package = __name__.split(".")[0]
    template_bytes = pkgutil.get_data(package, REPORTS_EXPORT_TEMPLATE_PATH)
    if template_bytes is None:
        raise FileNotFoundError(f"Unable to find {REPORTS_EXPORT_TEMPLATE_PATH} in the package.")
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


class ExpensifyReports(Stream):
    # Airbyte uses this to know what column uniquely identifies a row
    primary_key = "reportID"
    # Expensify has no native "updated at" column, so we derive one (see _compute_updated_at)
    # from the created/submitted/approved/reimbursed date columns. Declaring it here is what
    # enables the Incremental Append and Incremental Append + Deduped sync modes.
    cursor_field = UPDATED_AT_CURSOR_FIELD
    # Secondary, internal-only cursor (created/submitted only) used to resume/bound the export
    # window per Expensify's own startDate/endDate filter semantics (see EXPORT_CURSOR_FIELD).
    export_cursor_field = EXPORT_CURSOR_FIELD

    def __init__(
        self,
        name: str,
        partner_user_id: str,
        partner_user_secret: str,
        start_date: str,
        end_date: Optional[str] = None,
        report_state: Optional[List[str]] = None,
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

    @property
    def name(self) -> str:
        return self._name

    def get_updated_state(self, current_stream_state: Mapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        current_stream_state = current_stream_state or {}
        new_state = dict(current_stream_state)

        # `updatedAt` (created/submitted/approved/reimbursed) drives dedup.
        updated_at_candidates = [
            value for value in (current_stream_state.get(self.cursor_field), latest_record.get(self.cursor_field)) if value
        ]
        if updated_at_candidates:
            new_state[self.cursor_field] = max(updated_at_candidates)

        # `createdOrSubmittedAt` (created/submitted only) drives the export window.
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
        stream_state = stream_state or {}
        # For incremental syncs, resume the export window from the last synced cursor value
        # instead of re-exporting (and re-scanning) the full configured date range every time.
        state_export_cursor_value = stream_state.get(self.export_cursor_field) if sync_mode == SyncMode.incremental else None
        export_start_date = self.start_date
        if state_export_cursor_value:
            state_cursor_date = state_export_cursor_value[:10]  # Expensify's export filter is date-only (YYYY-MM-DD)
            export_start_date = max(self.start_date, state_cursor_date)

        if export_start_date > self.end_date:
            self.logger.info(
                f"Skipping export: resumed cursor date {export_start_date} is past the configured "
                f"end_date {self.end_date}. All data in the configured date range has already been synced."
            )
            return

        self.logger.info(
            f"Requesting Expensify export for {self.name} with filters: "
            f"startDate={export_start_date}, endDate={self.end_date}, "
            f"reportState={self.report_state or 'all'}."
        )

        try:
            # Step 1: Trigger the Export Job
            file_name = self._trigger_export(start_date=export_start_date)
        except ResourceNotFoundError as e:
            raise AirbyteTracedException(
                internal_message=str(e),
                message=("Expensify returned 'resource not found' (HTTP 410) while triggering the reports export. "),
                failure_type=FailureType.config_error,
            ) from e
        except CredentialsInvalidError as e:
            raise AirbyteTracedException(
                internal_message=str(e),
                message=(
                    "Expensify credentials are invalid (HTTP 401) while triggering the reports export. "
                    "Please verify your Partner User ID and Partner User Secret."
                ),
                failure_type=FailureType.config_error,
            ) from e
        self.logger.info(f"Triggered Expensify export for file {file_name}.")

        try:
            # Step 2: Download the CSV
            csv_data = self._download_file(file_name)
        except ResourceNotFoundError as e:
            # A 410 here means the exported file itself is not yet or no longer available.
            raise AirbyteTracedException(
                internal_message=str(e),
                message=(f"Expensify returned 'resource not found' (HTTP 410) while downloading the exported file '{file_name}'. "),
                failure_type=FailureType.config_error,
            ) from e
        except CredentialsInvalidError as e:
            raise AirbyteTracedException(
                internal_message=str(e),
                message=(
                    f"Expensify credentials are invalid (HTTP 401) while downloading the exported file '{file_name}'. "
                    "Please verify your Partner User ID and Partner User Secret."
                ),
                failure_type=FailureType.config_error,
            ) from e
        self.logger.info(f"Downloaded Expensify export ({len(csv_data)} bytes) for file {file_name}.")

        # Step 3: Parse CSV in memory and yield rows to Airbyte
        reader = csv.DictReader(StringIO(csv_data))
        raw_rows = list(reader)
        self.logger.info(f"Raw Expensify CSV export contains {len(raw_rows)} row(s).")
        record_count = 0
        for row in raw_rows:
            # Airbyte takes these yielded dicts, validates them against the schema,
            # and streams them to the destination connector.
            # Note: we intentionally do not filter out rows whose `updatedAt` is older than the
            # previous state value here. Doing so is unsafe once `start_date` is widened to
            # backfill older data, since the state's `updatedAt` reflects the last sync time (e.g.
            # "today"), not the export window, and would cause legitimately new (but old) rows to
            # be skipped. Incremental Append + Dedup handles unchanged/duplicate rows downstream.
            row[self.cursor_field] = _compute_updated_at(row)
            row[self.export_cursor_field] = _compute_export_cursor(row)
            record_count += 1
            yield row
        self.logger.info(f"Parsed {record_count} record(s) from Expensify export.")

    def _trigger_export(self, start_date: Optional[str] = None) -> str:
        input_settings = {
            "type": "combinedReportData",
            "filters": {
                "startDate": start_date if start_date is not None else self.start_date,
                "endDate": self.end_date,
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
        response = _post_job_description(job_description, template=_load_reports_export_template())
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


class SourceExpensify(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, Any]:
        # Validate that the provided credentials actually work
        try:
            # Request a non-existent policy to ensure credentials are valid
            job_description = {
                "type": "get",
                "credentials": {
                    "partnerUserID": config["partner_user_id"],
                    "partnerUserSecret": config["partner_user_secret"],
                },
                "inputSettings": {"type": "policy", "fields": ["reportFields"], "policyIDList": ["abc"]},
            }
            response = _post_job_description(job_description)
            # Ensure the response is valid JSON
            response.json()
            return True, None
        except ResourceNotFoundError:
            # Expensify returns 410 if the (deliberately non-existent) policy doesn't exist
            logger.info("Credentials are valid.")
            return True, None
        except CredentialsInvalidError:
            # Expensify returns 401 if the credentials are invalid
            logger.info("Credentials are invalid.")
            return False, None
        except Exception as e:
            logger.info(f"Other issue connecting to Expensify: {e}")
            return False, e

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        # Pass the credentials from the Airbyte UI into your stream
        return [
            ExpensifyReports(
                name="reports",
                partner_user_id=config["partner_user_id"],
                partner_user_secret=config["partner_user_secret"],
                start_date=config["start_date"],
                end_date=config.get("end_date"),
                report_state=config.get("report_state"),
            )
        ]
