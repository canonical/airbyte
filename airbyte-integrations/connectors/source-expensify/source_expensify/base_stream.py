# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import csv
import json
from io import StringIO
from typing import Any, Iterable, List, Mapping, Optional

import requests

from airbyte_cdk.models import FailureType, SyncMode
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http.exceptions import DefaultBackoffException, UserDefinedBackoffException
from airbyte_cdk.sources.streams.http.rate_limiting import default_backoff_handler, user_defined_backoff_handler
from airbyte_cdk.utils.traced_exception import AirbyteTracedException


EXPENSIFY_URL = "https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations"

MAX_RETRIES = 5
RETRY_FACTOR = 5
RATE_LIMIT_BACKOFF_SECONDS = 10.0


class PolicyNotFoundError(Exception):
    """Raised when the Expensify policy doesn't exist (HTTP 410)."""


class CredentialsInvalidError(Exception):
    """Raised when the Expensify credentials are invalid (HTTP 401)."""


class RateLimitExceededError(Exception):
    """Raised when the Expensify API rate limit is exceeded (HTTP 429)."""


def _map_response_code_to_exception(response_code: int) -> None:
    """Map an Expensify response code to an exception."""
    if response_code == requests.codes.gone:
        # Expensify returns 410 if the policy doesn't exist
        raise PolicyNotFoundError(f"Expensify policy not found.")
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
    response.raise_for_status()
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


class ExpensifyExportStream(Stream):
    """
    Base class for Expensify streams backed by the Integration Server's file export/download
    workflow (used by both the Reports and Expenses streams): trigger an export job for a
    combined CSV, download the resulting file, and parse it into records.

    Subclasses must set `primary_key` and `cursor_field`, and implement `_input_settings` (the
    export job's `inputSettings`), `_compute_cursor_value` (deriving the cursor value for a row),
    and optionally `_export_template` (an export-shaping FreeMarker template, if needed).
    """

    def __init__(self, name: str, partner_user_id: str, partner_user_secret: str, start_date: str, end_date: str, **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self.partner_user_id = partner_user_id
        self.partner_user_secret = partner_user_secret
        self.start_date = start_date
        self.end_date = end_date

    @property
    def name(self) -> str:
        return self._name

    def get_updated_state(self, current_stream_state: Mapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        current_cursor_value = (current_stream_state or {}).get(self.cursor_field)
        latest_cursor_value = latest_record.get(self.cursor_field)
        candidates = [value for value in (current_cursor_value, latest_cursor_value) if value]
        return {self.cursor_field: max(candidates)} if candidates else {}

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
        state_cursor_value = stream_state.get(self.cursor_field) if sync_mode == SyncMode.incremental else None
        export_start_date = self.start_date
        if state_cursor_value:
            state_cursor_date = state_cursor_value[:10]  # Expensify's export filter is date-only (YYYY-MM-DD)
            export_start_date = max(self.start_date, state_cursor_date)

        # Step 1: Trigger the Export Job
        file_name = self._trigger_export(start_date=export_start_date)
        self.logger.info(f"Triggered Expensify export for file {file_name}.")

        # Step 2: Download the CSV
        csv_data = self._download_file(file_name)
        self.logger.info(f"Downloaded Expensify export ({len(csv_data)} bytes) for file {file_name}.")

        # Step 3: Parse CSV in memory and yield rows to Airbyte
        reader = csv.DictReader(StringIO(csv_data))
        record_count = 0
        skipped_count = 0
        for row in reader:
            # Airbyte takes these yielded dicts, validates them against the schema,
            # and streams them to the destination connector
            row[self.cursor_field] = self._compute_cursor_value(row)
            if state_cursor_value and (row[self.cursor_field] or "") <= state_cursor_value:
                # Already synced in a previous run
                skipped_count += 1
                continue
            record_count += 1
            yield row
        self.logger.info(f"Parsed {record_count} record(s) from Expensify export (skipped {skipped_count} already-synced record(s)).")

    def _trigger_export(self, start_date: Optional[str] = None) -> str:
        job_description = {
            "type": "file",
            "credentials": {
                "partnerUserID": self.partner_user_id,
                "partnerUserSecret": self.partner_user_secret,
            },
            "onReceive": {"immediateResponse": ["returnRandomFileName"]},
            "inputSettings": self._input_settings(start_date),
            "outputSettings": {"fileExtension": "csv"},
        }
        response = _post_job_description(job_description, template=self._export_template())
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

    def _input_settings(self, start_date: Optional[str]) -> Mapping[str, Any]:
        """Build the export job's `inputSettings` (export type, date filters, etc.)."""
        raise NotImplementedError

    def _export_template(self) -> Optional[str]:
        """Return the FreeMarker template (if any) used to shape the exported CSV."""
        return None

    def _compute_cursor_value(self, row: Mapping[str, Any]) -> Optional[str]:
        """Derive this stream's cursor value for a parsed CSV row."""
        raise NotImplementedError
