# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""
Integration-style tests that drive the connector through its actual Airbyte CLI entrypoint
(discover/read), using the `configured_catalog_incremental.json`, `sample_state.json`, and
`abnormal_state.json` fixtures in this directory.
"""

import json
from pathlib import Path
from typing import Any, List, Mapping
from unittest.mock import Mock
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
    # Disabled here so existing assertions about the resumed export window's exact start_date are
    # unaffected by the lookback window; the lookback window itself is covered by
    # `TestIncrementalLookbackWindow` below.
    "lookback_window_days": 0,
}

# Report 101 and 102 were "already synced" as of sample_state.json's cursor (2026-08-16);
# only report 103 is newer and should be re-emitted on a resumed sync.
CSV_DATA = "reportID,created\n101,2026-08-01\n102,2026-08-15\n103,2026-08-31\n"


def _load_json_config(file_name: str) -> Mapping[str, Any]:
    return json.loads((INTEGRATION_TESTS_DIR / file_name).read_text())


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


class TestCheck:
    """`check`/`discover`/`read` failure-path coverage using the realistic `sample_config.json`
    (succeeds) and `invalid_config.json` (fails authentication) fixtures in this directory."""

    def test_check_succeeds_with_valid_config(self, requests_mock):
        # Expensify returns 410 ("resource not found") for the deliberately non-existent policy
        # requested by `check_connection`; that response confirms the credentials themselves are
        # valid even though the policy doesn't exist.
        requests_mock.post(EXPENSIFY_URL, json={"responseMessage": "Not found", "responseCode": 410})

        is_available, error = SourceExpensify().check_connection(logger=Mock(), config=_load_json_config("sample_config.json"))

        assert is_available is True
        assert error is None

    def test_check_fails_with_invalid_config(self, requests_mock):
        # Expensify returns 401 for invalid partner credentials.
        requests_mock.post(EXPENSIFY_URL, json={"responseMessage": "Unauthorized", "responseCode": 401})

        is_available, error = SourceExpensify().check_connection(logger=Mock(), config=_load_json_config("invalid_config.json"))

        assert is_available is False


class TestReadFailurePaths:
    def test_read_fails_with_invalid_authentication(self, requests_mock):
        # Invalid credentials surface as a 401 when triggering the export job; `read` should
        # report this as a config-error trace rather than emit any records.
        requests_mock.post(
            EXPENSIFY_URL,
            additional_matcher=lambda request: _job_type(request) == "file",
            json={"responseMessage": "Unauthorized", "responseCode": 401},
        )

        output = read(
            SourceExpensify(),
            _load_json_config("invalid_config.json"),
            _load_incremental_catalog(),
            expecting_exception=True,
        )

        assert output.records == []
        assert any(
            trace.trace.error is not None and "credentials are invalid" in trace.trace.error.message.lower()
            for trace in output.trace_messages
        )


class TestIncrementalStateProgression:
    def test_initial_sync_emits_all_records_and_final_state(self, requests_mock):
        _mock_expensify_export(requests_mock, CSV_DATA)

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog())

        record_ids = sorted(r.record.data["reportID"] for r in output.records)
        assert record_ids == ["101", "102", "103"]
        assert output.most_recent_state.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"

    def test_resumed_sync_with_sample_state_does_not_skip_records_by_updated_at(self, requests_mock):
        _mock_expensify_export(requests_mock, CSV_DATA)
        state = _load_legacy_state("sample_state.json")

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(), state=state)

        # All records returned by the export are emitted; the connector no longer filters rows
        # locally by comparing `updatedAt` against the resumed state (see regression test below).
        record_ids = [r.record.data["reportID"] for r in output.records]
        assert record_ids == ["101", "102", "103"]
        assert output.most_recent_state.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        assert (
            _triggered_start_date(trigger_request) == "2026-08-16"
        ), "Export window should resume from the state cursor, not the configured start_date"

    def test_resumed_sync_with_abnormal_future_state_yields_no_records(self, requests_mock):
        _mock_expensify_export(requests_mock, CSV_DATA)
        state = _load_legacy_state("abnormal_state.json")

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(), state=state)

        assert output.records == []

    def test_resumed_sync_not_skipped_when_only_reimbursed_date_is_past_end_date(self, requests_mock):
        # Regression test: report 103 was created 2026-08-31 (within the configured start/end_date
        # window) but reimbursed 2026-09-05, after the configured end_date (2026-09-01). The prior
        # sync's state therefore has a stale `updatedAt` past end_date, even though
        # `createdOrSubmittedAt` is still within range. The resumed sync must still run (using
        # `createdOrSubmittedAt` to resume the export window) instead of skipping entirely.
        csv_data = "reportID,created,reimbursed\n101,2026-08-01,\n102,2026-08-15,\n103,2026-08-31,2026-09-05\n"
        _mock_expensify_export(requests_mock, csv_data)
        state = _load_legacy_state("sample_state.json")

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(), state=state)

        record_ids = [r.record.data["reportID"] for r in output.records]
        assert record_ids == ["101", "102", "103"]

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        assert (
            _triggered_start_date(trigger_request) == "2026-08-16"
        ), "Export window should resume from createdOrSubmittedAt, not the stale (reimbursed-inflated) updatedAt"

    def test_widened_start_date_backfills_past_records_without_skipping(self, requests_mock):
        # Regression test: if the user widens `start_date` to backfill data further in the past
        # than a previous sync's state reflects, previously-unseen records with an `updatedAt`
        # older than the state's `updatedAt` must still be emitted. The state's `updatedAt` only
        # reflects the last sync's cursor (effectively "today" at the time it ran), not the
        # export window, so it must never be used to filter out rows once the configured
        # start_date is widened backward.
        widened_config = {**CONFIG, "start_date": "2020-01-01"}
        # Report 201 falls well before the state's cursor (2026-08-16) - it's newly in-scope only
        # because start_date was widened, and must not be skipped. Report 103 is unaffected.
        csv_data = "reportID,created\n201,2020-06-15\n103,2026-08-31\n"
        _mock_expensify_export(requests_mock, csv_data)
        state = _load_legacy_state("sample_state.json")

        output = read(SourceExpensify(), widened_config, _load_incremental_catalog(), state=state)

        record_ids = [r.record.data["reportID"] for r in output.records]
        assert record_ids == ["201", "103"], "Widening start_date into the past must not skip older, newly in-scope records"

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        assert (
            _triggered_start_date(trigger_request) == "2026-08-16"
        ), "Export window still resumes from the (newer) state cursor, not the widened start_date"


class TestIncrementalLookbackWindow:
    def test_lookback_window_replays_report_approved_after_previous_sync(self, requests_mock):
        # End-to-end regression test for `lookback_window_days`: report 201 was created before
        # the state's export cursor (2026-08-16), so a strict resume (lookback disabled) would
        # never re-export it, even though it was approved after the previous sync ran. With a
        # 30-day lookback, the resumed export window trails back far enough to include it again.
        lookback_config = {**CONFIG, "lookback_window_days": 30}
        csv_data = "reportID,created,approved\n201,2026-08-10,2026-08-20\n103,2026-08-31,\n"
        _mock_expensify_export(requests_mock, csv_data)
        state = _load_legacy_state("sample_state.json")

        output = read(SourceExpensify(), lookback_config, _load_incremental_catalog(), state=state)

        record_ids = [r.record.data["reportID"] for r in output.records]
        assert record_ids == ["201", "103"]

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        # State cursor (2026-08-16) trailed back by the 30-day lookback window -> 2026-07-17.
        assert _triggered_start_date(trigger_request) == "2026-07-17"

    def test_lookback_window_never_precedes_configured_start_date(self, requests_mock):
        # The lookback window must not push the resumed export start earlier than the configured
        # start_date, which remains a hard lower bound.
        lookback_config = {**CONFIG, "start_date": "2026-08-01", "lookback_window_days": 30}
        csv_data = "reportID,created\n103,2026-08-31\n"
        _mock_expensify_export(requests_mock, csv_data)
        state = _load_legacy_state("sample_state.json")

        read(SourceExpensify(), lookback_config, _load_incremental_catalog(), state=state)

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        # 2026-08-16 minus 30 days = 2026-07-17, which is before the configured start_date
        # (2026-08-01), so the configured start_date wins.
        assert _triggered_start_date(trigger_request) == "2026-08-01"

    def test_widened_start_date_beyond_lookback_window_still_requires_state_reset(self, requests_mock):
        # Widening start_date further into the past than the lookback window reaches does not, by
        # itself, backfill that older data - a state reset (or full refresh) is still required.
        widened_config = {**CONFIG, "start_date": "2020-01-01", "lookback_window_days": 30}
        csv_data = "reportID,created\n103,2026-08-31\n"
        _mock_expensify_export(requests_mock, csv_data)
        state = _load_legacy_state("sample_state.json")

        read(SourceExpensify(), widened_config, _load_incremental_catalog(), state=state)

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        # The resumed export still only trails back 30 days from the state cursor (2026-07-17),
        # not all the way back to the widened start_date (2020-01-01).
        assert _triggered_start_date(trigger_request) == "2026-07-17"
