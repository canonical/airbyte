from typing import Any, Iterable, List, Mapping, Optional, Tuple
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.models import SyncMode
import requests
import time
import csv
from io import StringIO

EXPENSIFY_URL = "https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations"

class ExpensifyReports(Stream):
    # Airbyte uses this to know what column uniquely identifies a row
    primary_key = "reportID"

    def __init__(self, partner_user_id: str, partner_user_secret: str, **kwargs):
        super().__init__(**kwargs)
        self.partner_user_id = partner_user_id
        self.partner_user_secret = partner_user_secret

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        
        # Step 1: Trigger the Export Job
        file_name = self._trigger_export()

        # Step 2: Poll until the file is ready
        self._wait_for_file(file_name)

        # Step 3: Download the CSV
        csv_data = self._download_file(file_name)

        # Step 4: Parse CSV in memory and yield rows to Airbyte
        reader = csv.DictReader(StringIO(csv_data))
        for row in reader:
            # Airbyte takes these yielded dicts, validates them against your schema, 
            # and streams them to Postgres
            yield row

    def _trigger_export(self) -> str:
        payload = {
            "requestJobDescription": {
                "type": "file",
                "credentials": {
                    "partnerUserID": self.partner_user_id,
                    "partnerUserSecret": self.partner_user_secret
                },
                "onReceive": {"immediateResponse": ["returnRandomFileName"]},
                "inputSettings": {"type": "combinedReportData"},
                "outputSettings": {"fileExtension": "csv"}
            },
            # Tell Expensify exactly what columns to output
            "template": "<#list reports as report>${report.reportID},${report.amount}<#lt></#list>"
        }
        response = requests.post(EXPENSIFY_URL, data=payload)
        response.raise_for_status()
        return response.text.strip()

    def _wait_for_file(self, file_name: str):
        # Polling loop: Expensify returns a 400 or 500 series error if the file isn't ready yet
        max_retries = 20
        for _ in range(max_retries):
            payload = {
                "requestJobDescription": {
                    "type": "download",
                    "credentials": {
                        "partnerUserID": self.partner_user_id,
                        "partnerUserSecret": self.partner_user_secret
                    },
                    "fileName": file_name,
                    "fileSystem": "integrationServer"
                }
            }
            response = requests.post(EXPENSIFY_URL, data=payload)
            if response.status_code == 200:
                return # File is ready
            time.sleep(30) # Wait 30 seconds before polling again
            
        raise Exception(f"Expensify file {file_name} failed to generate in time.")

    def _download_file(self, file_name: str) -> str:
        # Re-request the download now that we know it's ready
        payload = {
             # ... same payload as _wait_for_file ...
        }
        response = requests.post(EXPENSIFY_URL, data=payload)
        response.raise_for_status()
        return response.text


class SourceExpensify(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, any]:
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
                partner_user_id=config["partner_user_id"],
                partner_user_secret=config["partner_user_secret"]
            )
        ]
