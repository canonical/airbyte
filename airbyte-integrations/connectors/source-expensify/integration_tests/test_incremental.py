# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""
Integration-style tests that drive the connector through its actual Airbyte CLI entrypoint
(discover/read), using the `configured_catalog_incremental.json`, `sample_state.json`, and
`abnormal_state.json` fixtures in this directory.
"""

import json
from pathlib import Path
from typing import Any, List, Mapping
from urllib.parse import parse_qs

from source_expensify.source import EXPENSIFY_URL, SourceExpensify

from airbyte_cdk.models import (
    AirbyteStateBlob,
    AirbyteStateMessage,
    AirbyteStateType,
    AirbyteStreamState,
    ConfiguredAirbyteCatalogSerializer,
    StreamDescriptor,
    SyncMode,
)
from airbyte_cdk.test.entrypoint_wrapper import discover, read


INTEGRATION_TESTS_DIR = Path(__file__).parent

CONFIG: Mapping[str, Any] = {
    "partner_user_id": "test-partner-id",
    "partner_user_secret": "test-partner-secret",
    "start_date": "2026-07-01",
    "end_date": "2026-09-01",
}

# Report 101 and 102 were "already synced" as of sample_state.json's cursor (2026-08-16);
# only report 103 is newer and should be re-emitted on a resumed sync.
CSV_DATA = "reportID,created\n101,2026-08-01\n102,2026-08-15\n103,2026-08-31\n"


def _load_incremental_catalog():
    catalog_path = INTEGRATION_TESTS_DIR / "configured_catalog_incremental.json"
    return ConfiguredAirbyteCatalogSerializer.load(json.loads(catalog_path.read_text()))


def _load_legacy_state(file_name: str) -> List[AirbyteStateMessage]:
    """Convert a legacy `{stream_name: {cursor_field: value}}` state fixture into the modern
    per-stream `AirbyteStateMessage` list expected by the CDK's `read()` test helper."""
    legacy_state = json.loads((INTEGRATION_TESTS_DIR / file_name).read_text())
    return [
        AirbyteStateMessage(
            type=AirbyteStateType.STREAM,
            stream=AirbyteStreamState(
                stream_descriptor=StreamDescriptor(name=stream_name),
                stream_state=AirbyteStateBlob(stream_state),
            ),
        )
        for stream_name, stream_state in legacy_state.items()
    ]


def _job_type(request) -> str:
    form = parse_qs(request.text)
    return json.loads(form["requestJobDescription"][0])["type"]


def _triggered_start_date(request) -> str:
    form = parse_qs(request.text)
    job_description = json.loads(form["requestJobDescription"][0])
    return job_description["inputSettings"]["filters"]["startDate"]


def _mock_expensify_export(requests_mock, csv_data: str, file_name: str = "combined_report.csv") -> None:
    requests_mock.post(
        EXPENSIFY_URL,
        additional_matcher=lambda request: _job_type(request) == "file",
        text=file_name,
    )
    requests_mock.post(
        EXPENSIFY_URL,
        additional_matcher=lambda request: _job_type(request) == "download",
        text=csv_data,
    )


class TestDiscover:
    def test_discover_reports_supports_incremental(self, requests_mock):
        output = discover(SourceExpensify(), CONFIG)

        reports_stream = next(s for s in output.catalog.catalog.streams if s.name == "reports")
        assert SyncMode.incremental in reports_stream.supported_sync_modes
        assert reports_stream.source_defined_cursor is True
        assert reports_stream.default_cursor_field == ["updatedAt"]


class TestIncrementalStateProgression:
    def test_initial_sync_emits_all_records_and_final_state(self, requests_mock):
        _mock_expensify_export(requests_mock, CSV_DATA)

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog())

        record_ids = sorted(r.record.data["reportID"] for r in output.records)
        assert record_ids == ["101", "102", "103"]
        assert output.most_recent_state.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"

    def test_resumed_sync_with_sample_state_skips_already_synced_records(self, requests_mock):
        _mock_expensify_export(requests_mock, CSV_DATA)
        state = _load_legacy_state("sample_state.json")

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(), state=state)

        record_ids = [r.record.data["reportID"] for r in output.records]
        assert record_ids == ["103"], "Only records newer than the resumed state's cursor should be re-emitted"
        assert output.most_recent_state.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        assert _triggered_start_date(trigger_request) == "2026-08-16", (
            "Export window should resume from the state cursor, not the configured start_date"
        )

    def test_resumed_sync_with_abnormal_future_state_yields_no_records(self, requests_mock):
        _mock_expensify_export(requests_mock, CSV_DATA)
        state = _load_legacy_state("abnormal_state.json")

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(), state=state)

        assert output.records == []
