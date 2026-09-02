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

from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream


EXPENSIFY_URL = "https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations"
RAW_CSV_DEBUG_DIR = Path("/tmp/source_expensify_debug")
REPORTS_EXPORT_TEMPLATE_PATH = "templates/reports_export_template.ftl"


def _load_reports_export_template() -> str:
    """Load the Expensify export template used to shape the combined report CSV output."""
    package = __name__.split(".")[0]
    template_bytes = pkgutil.get_data(package, REPORTS_EXPORT_TEMPLATE_PATH)
    if template_bytes is None:
        raise FileNotFoundError(f"Unable to find {REPORTS_EXPORT_TEMPLATE_PATH} in the package.")
    return template_bytes.decode("utf-8")


def _post_job_description(job_description: Mapping[str, Any], template: Optional[str] = None) -> requests.Response:
    """
    Send a requestJobDescription to the Expensify Integration Server.

    Expensify requires the `requestJobDescription` form field to be a JSON-encoded
    string, not a native Python dict - requests would otherwise form-encode it using
    Python's repr() (single quotes, True/False), which Expensify rejects as invalid JSON.

    `template` (when provided) must be sent as its own top-level form field, sibling to
    `requestJobDescription`, not nested inside it - Expensify rejects nested templates
    with "No Template Submitted".
    """
    payload = {"requestJobDescription": json.dumps(job_description)}
    if template is not None:
        payload["template"] = template
    response = requests.post(EXPENSIFY_URL, data=payload, timeout=60)
    response.raise_for_status()

    # Expensify returns HTTP 200 even for some error conditions, with a JSON error body
    # like {"responseMessage": "...", "responseCode": 500}. Detect and surface those.
    stripped = response.text.strip()
    if stripped.startswith("{") and '"responseCode"' in stripped:
        try:
            error_body = json.loads(stripped)
        except json.JSONDecodeError:
            error_body = None
        if error_body and "responseCode" in error_body:
            raise Exception(f"Expensify API error: {error_body.get('responseMessage', stripped)}")

    return response


class ExpensifyReports(Stream):
    # Airbyte uses this to know what column uniquely identifies a row
    primary_key = "reportID"

    def __init__(self, name: str, partner_user_id: str, partner_user_secret: str, **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self.partner_user_id = partner_user_id
        self.partner_user_secret = partner_user_secret

    @property
    def name(self) -> str:
        return self._name

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        self.logger.info(f"Reading records from Expensify for {self.name}")
        # Step 1: Trigger the Export Job
        file_name = self._trigger_export()
        self.logger.info(f"Triggered Expensify export for file {file_name}.")

        # Step 2: Poll until the file is ready
        self._wait_for_file(file_name)
        self.logger.info(f"Expensify export file {file_name} is ready.")

        # Step 3: Download the CSV
        csv_data = self._download_file(file_name)
        self.logger.info(f"Downloaded Expensify export ({len(csv_data)} bytes) for file {file_name}.")
        debug_path = self._store_raw_csv(csv_data, file_name)
        self.logger.info(f"Stored raw Expensify CSV export at {debug_path} for debugging.")

        # Step 4: Parse CSV in memory and yield rows to Airbyte
        reader = csv.DictReader(StringIO(csv_data))
        record_count = 0
        for row in reader:
            # Airbyte takes these yielded dicts, validates them against your schema,
            # and streams them to Postgres
            record_count += 1
            yield row
        self.logger.info(f"Parsed {record_count} record(s) from Expensify export.")

    def _trigger_export(self) -> str:
        job_description = {
            "type": "file",
            "credentials": {
                "partnerUserID": self.partner_user_id,
                "partnerUserSecret": self.partner_user_secret,
            },
            "onReceive": {"immediateResponse": ["returnRandomFileName"]},
            "inputSettings": {
                "type": "combinedReportData",
                "filters": {
                    "startDate": "2026-08-30",
                    "endDate": "2026-08-31",
                },
                "reportState": "REIMBURSED",
            },
            "outputSettings": {"fileExtension": "csv"},
        }
        # Tell Expensify exactly what columns to output
        response = _post_job_description(job_description, template=_load_reports_export_template())
        return response.text.strip()

    def _wait_for_file(self, file_name: str):
        # Polling loop: Expensify returns a 400 or 500 series error if the file isn't ready yet
        max_retries = 20
        job_description = {
            "type": "download",
            "credentials": {"partnerUserID": self.partner_user_id, "partnerUserSecret": self.partner_user_secret},
            "fileName": file_name,
            "fileSystem": "integrationServer",
        }
        for attempt in range(max_retries):
            try:
                _post_job_description(job_description)
                self.logger.info(f"Expensify file {file_name} is ready after {attempt + 1} attempt(s).")
                return  # File is ready
            except Exception as error:
                self.logger.info(
                    f"Expensify file {file_name} not ready yet ({error}), retrying in 30s (attempt {attempt + 1}/{max_retries})."
                )
                time.sleep(30)  # Wait 30 seconds before polling again

        raise Exception(f"Expensify file {file_name} failed to generate in time.")

    def _download_file(self, file_name: str) -> str:
        # Re-request the download now that we know it's ready
        job_description = {
            "type": "download",
            "credentials": {"partnerUserID": self.partner_user_id, "partnerUserSecret": self.partner_user_secret},
            "fileName": file_name,
            "fileSystem": "integrationServer",
        }
        response = _post_job_description(job_description)
        return response.text

    def _store_raw_csv(self, csv_data: str, file_name: str) -> Path:
        """Persist the raw CSV export to disk for debugging purposes."""
        RAW_CSV_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe_file_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in file_name)
        suffix = "" if safe_file_name.lower().endswith(".csv") else ".csv"
        debug_path = RAW_CSV_DEBUG_DIR / f"{timestamp}_{safe_file_name}{suffix}"
        debug_path.write_text(csv_data, encoding="utf-8")
        return debug_path


class SourceExpensify(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, Any]:
        # Validate that the provided credentials actually work
        try:
            # You can trigger a tiny dummy request here to ensure credentials are valid
            return True, None
        except Exception as e:
            return False, e

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        # Pass the credentials from the Airbyte UI into your stream
        return [
            ExpensifyReports(
                name="reports",
                partner_user_id=config["partner_user_id"],
                partner_user_secret=config["partner_user_secret"],
            )
        ]
