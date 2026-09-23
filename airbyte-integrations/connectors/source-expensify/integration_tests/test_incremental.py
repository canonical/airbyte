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

from source_expensify.base_stream import EXPENSIFY_URL
from source_expensify.source import SourceExpensify

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

# Expenses analogue of CSV_DATA/sample_state.json above: transaction 1 and 2 were "already
# synced" as of the expenses sample state's cursor (2026-08-16); only transaction 3 is newer.
EXPENSES_CSV_DATA = "transactionID,created\n1,2026-08-01\n2,2026-08-15\n3,2026-08-31\n"
EXPENSES_SAMPLE_STATE = {"expenses": {"updatedAt": "2026-08-16T00:00:00+00:00", "createdAt": "2026-08-16T00:00:00+00:00"}}
EXPENSES_ABNORMAL_STATE = {"expenses": {"updatedAt": "2222-01-01T00:00:00+00:00", "createdAt": "2222-01-01T00:00:00+00:00"}}


def _load_json_config(file_name: str) -> Mapping[str, Any]:
    return json.loads((INTEGRATION_TESTS_DIR / file_name).read_text())


def _load_incremental_catalog(stream_names: List[str] = ("reports",)):
    """Load `configured_catalog_incremental.json`, filtered down to only `stream_names`.

    The on-disk catalog declares both `reports` and `expenses` (so `test_discover_*`-style
    coverage sees both), but most of the tests below only mock/assert one stream at a time;
    defaulting to `("reports",)` and requiring callers to opt in to `expenses` keeps each test's
    catalog, mocks, and assertions in sync with each other.
    """
    catalog_path = INTEGRATION_TESTS_DIR / "configured_catalog_incremental.json"
    raw_catalog = json.loads(catalog_path.read_text())
    raw_catalog = {**raw_catalog, "streams": [s for s in raw_catalog["streams"] if s["stream"]["name"] in stream_names]}
    return ConfiguredAirbyteCatalogSerializer.load(raw_catalog)


def _state_messages(legacy_state: Mapping[str, Mapping[str, Any]]) -> List[AirbyteStateMessage]:
    """Convert a legacy `{stream_name: {cursor_field: value}}` state mapping into the modern
    per-stream `AirbyteStateMessage` list expected by the CDK's `read()` test helper."""
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


def _load_legacy_state(file_name: str) -> List[AirbyteStateMessage]:
    """Load a legacy `{stream_name: {cursor_field: value}}` state fixture from disk and convert
    it via `_state_messages`."""
    return _state_messages(json.loads((INTEGRATION_TESTS_DIR / file_name).read_text()))


def _job_type(request) -> str:
    form = parse_qs(request.text)
    return json.loads(form["requestJobDescription"][0])["type"]


def _triggered_start_date(request) -> str:
    form = parse_qs(request.text)
    job_description = json.loads(form["requestJobDescription"][0])
    return job_description["inputSettings"]["filters"]["startDate"]


def _triggered_template(request) -> str:
    return parse_qs(request.text)["template"][0]


def _downloaded_file_name(request) -> str:
    form = parse_qs(request.text)
    return json.loads(form["requestJobDescription"][0])["fileName"]


def _mock_expensify_export(requests_mock, csv_data: str, file_name: str = "combined_report.csv") -> None:
    """Mock a single stream's export trigger/download round-trip, regardless of which stream
    triggers it. Only safe to use when at most one stream is present in the configured catalog -
    with two streams sharing this shared export endpoint, both would otherwise be routed through
    the same trigger/download responses. Use `_mock_expensify_exports` for multi-stream catalogs.
    """
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


def _mock_expensify_exports(requests_mock, reports_csv_data: str = None, expenses_csv_data: str = None) -> None:
    """Mock export trigger/download round-trips for reports and/or expenses independently,
    distinguishing the two by the (stream-specific) FreeMarker template sent alongside the
    "file" trigger request - the expenses template is the only one containing "transactionID".
    """
    if reports_csv_data is not None:
        requests_mock.post(
            EXPENSIFY_URL,
            additional_matcher=lambda request: _job_type(request) == "file" and "transactionID" not in _triggered_template(request),
            text="reports_export.csv",
        )
        requests_mock.post(
            EXPENSIFY_URL,
            additional_matcher=lambda request: _job_type(request) == "download" and _downloaded_file_name(request) == "reports_export.csv",
            text=reports_csv_data,
        )
    if expenses_csv_data is not None:
        requests_mock.post(
            EXPENSIFY_URL,
            additional_matcher=lambda request: _job_type(request) == "file" and "transactionID" in _triggered_template(request),
            text="expenses_export.csv",
        )
        requests_mock.post(
            EXPENSIFY_URL,
            additional_matcher=lambda request: _job_type(request) == "download" and _downloaded_file_name(request) == "expenses_export.csv",
            text=expenses_csv_data,
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
        assert output.most_recent_state.stream_state.createdOrSubmittedAt == "2026-08-31T00:00:00+00:00"

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

    def test_widened_start_date_without_reset_does_not_backfill_past_records(self, requests_mock):
        # Regression test: widening start_date alone, without resetting state, does not backfill
        # older data - the export window is still bound by the (newer) state cursor (2026-08-16).
        widened_config = {**CONFIG, "start_date": "2020-01-01"}
        # Expensify, queried with startDate=2026-08-16, never returns rows older than that.
        csv_data = "reportID,created\n103,2026-08-31\n"
        _mock_expensify_export(requests_mock, csv_data)
        state = _load_legacy_state("sample_state.json")

        output = read(SourceExpensify(), widened_config, _load_incremental_catalog(), state=state)

        record_ids = [r.record.data["reportID"] for r in output.records]
        assert record_ids == ["103"]

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        assert _triggered_start_date(trigger_request) == "2026-08-16"

    def test_state_reset_with_widened_start_date_backfills_past_records(self, requests_mock):
        # Complement to the test above: a full refresh ignores prior state, so the widened
        # start_date takes effect and Expensify legitimately returns older records.
        widened_config = {**CONFIG, "start_date": "2020-01-01"}
        csv_data = "reportID,created\n201,2020-06-15\n103,2026-08-31\n"
        _mock_expensify_export(requests_mock, csv_data)

        output = read(SourceExpensify(), widened_config, _load_incremental_catalog())  # no prior state = reset

        record_ids = [r.record.data["reportID"] for r in output.records]
        assert record_ids == ["201", "103"]

        trigger_request = next(r for r in requests_mock.request_history if _job_type(r) == "file")
        assert _triggered_start_date(trigger_request) == "2020-01-01"


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


class TestIncrementalExpenses:
    """Expenses-stream analogues of `TestIncrementalStateProgression`'s coverage, using a
    single-stream (`expenses`-only) catalog and expenses-shaped CSV/state fixtures so these
    assertions stay valid independent of what `reports` is doing."""

    def _expenses_trigger_request(self, requests_mock):
        return next(r for r in requests_mock.request_history if _job_type(r) == "file")

    def test_initial_sync_emits_all_records_and_final_state(self, requests_mock):
        _mock_expensify_exports(requests_mock, expenses_csv_data=EXPENSES_CSV_DATA)

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(["expenses"]))

        record_ids = sorted(r.record.data["transactionID"] for r in output.records)
        assert record_ids == ["1", "2", "3"]
        assert output.most_recent_state.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"
        assert output.most_recent_state.stream_state.createdAt == "2026-08-31T00:00:00+00:00"

    def test_resumed_sync_with_sample_state_resumes_export_window_from_state_cursor(self, requests_mock):
        _mock_expensify_exports(requests_mock, expenses_csv_data=EXPENSES_CSV_DATA)
        state = _state_messages(EXPENSES_SAMPLE_STATE)

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(["expenses"]), state=state)

        record_ids = [r.record.data["transactionID"] for r in output.records]
        assert record_ids == ["1", "2", "3"]
        assert output.most_recent_state.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"

        trigger_request = self._expenses_trigger_request(requests_mock)
        assert (
            _triggered_start_date(trigger_request) == "2026-08-16"
        ), "Export window should resume from the state cursor, not the configured start_date"

    def test_resumed_sync_with_abnormal_future_state_yields_no_records(self, requests_mock):
        _mock_expensify_exports(requests_mock, expenses_csv_data=EXPENSES_CSV_DATA)
        state = _state_messages(EXPENSES_ABNORMAL_STATE)

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(["expenses"]), state=state)

        assert output.records == []


class TestIncrementalMultiStreamCatalog:
    """`configured_catalog_incremental.json` declares both `reports` and `expenses`; this class
    exercises a `read()` against the full, unfiltered catalog to confirm the two streams are
    synced independently within a single sync - each honoring only its own state and neither
    stream's mocked data or state bleeding into the other's output."""

    def test_read_with_both_streams_syncs_each_independently(self, requests_mock):
        _mock_expensify_exports(requests_mock, reports_csv_data=CSV_DATA, expenses_csv_data=EXPENSES_CSV_DATA)
        # Only reports has prior state; expenses should still sync (from start_date) rather than
        # being skipped, and should not inherit reports' state or vice versa.
        state = _state_messages(json.loads((INTEGRATION_TESTS_DIR / "sample_state.json").read_text()))

        output = read(SourceExpensify(), CONFIG, _load_incremental_catalog(["reports", "expenses"]), state=state)

        report_records = [r.record.data["reportID"] for r in output.records if r.record.stream == "reports"]
        expense_records = [r.record.data["transactionID"] for r in output.records if r.record.stream == "expenses"]
        # Both streams' mocked exports return all rows regardless of the requested startDate (see
        # `test_resumed_sync_with_sample_state_does_not_skip_records_by_updated_at` above), so all
        # records are emitted for both streams; what this test actually verifies is that reports'
        # export resumes from its state cursor while expenses' (state-less) export does not.
        assert report_records == ["101", "102", "103"]
        assert expense_records == ["1", "2", "3"]

        reports_state = next(s for s in output.state_messages if s.state.stream.stream_descriptor.name == "reports")
        expenses_state = next(s for s in output.state_messages if s.state.stream.stream_descriptor.name == "expenses")
        assert reports_state.state.stream.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"
        assert expenses_state.state.stream.stream_state.updatedAt == "2026-08-31T00:00:00+00:00"

        reports_trigger = next(
            r for r in requests_mock.request_history if _job_type(r) == "file" and "transactionID" not in _triggered_template(r)
        )
        expenses_trigger = next(
            r for r in requests_mock.request_history if _job_type(r) == "file" and "transactionID" in _triggered_template(r)
        )
        # reports resumes from sample_state.json's cursor (2026-08-16); expenses has no prior
        # state, so its export window starts from the configured start_date instead - confirming
        # each stream's export window is governed only by its own state.
        assert _triggered_start_date(reports_trigger) == "2026-08-16"
        assert _triggered_start_date(expenses_trigger) == "2026-07-01"
