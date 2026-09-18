# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
import yaml
from source_expensify.source import (
    DEFAULT_LOOKBACK_WINDOW_DAYS,
    EXPENSIFY_URL,
    CredentialsInvalidError,
    ExpensifyReports,
    RateLimitExceededError,
    ResourceNotFoundError,
    SourceExpensify,
    _post_job_description,
    _send_request,
)

from airbyte_cdk.models import FailureType, SyncMode
from airbyte_cdk.utils.traced_exception import AirbyteTracedException


@pytest.fixture
def stream():
    return ExpensifyReports(
        name="reports",
        partner_user_id="user-id",
        partner_user_secret="user-secret",
        start_date="2026-08-30",
        end_date="2026-08-31",
    )


class TestReadRecords:
    def test_read_records_yields_parsed_csv_rows(self, stream):
        csv_data = "reportID,amount\n1,100\n2,200\n"

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data) as mock_download,
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        mock_trigger.assert_called_once_with(start_date="2026-08-30")
        mock_download.assert_called_once_with("report.csv")

        assert records == [
            {"reportID": "1", "amount": "100", "updatedAt": None, "createdOrSubmittedAt": None},
            {"reportID": "2", "amount": "200", "updatedAt": None, "createdOrSubmittedAt": None},
        ]

    def test_read_records_no_rows(self, stream):
        csv_data = "reportID,amount\n"

        with (
            patch.object(stream, "_trigger_export", return_value="empty.csv"),
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert records == []

    def test_read_records_calls_steps_in_order(self, stream):
        call_order = []

        def trigger_export(start_date=None):
            call_order.append("trigger")
            return "file.csv"

        def download_file(file_name):
            call_order.append("download")
            assert file_name == "file.csv"
            return "reportID,amount\n1,50\n"

        with (
            patch.object(stream, "_trigger_export", side_effect=trigger_export),
            patch.object(stream, "_download_file", side_effect=download_file),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert call_order == ["trigger", "download"]
        assert records == [{"reportID": "1", "amount": "50", "updatedAt": None, "createdOrSubmittedAt": None}]

    def test_read_records_propagates_trigger_export_error(self, stream):
        with (
            patch.object(stream, "_trigger_export", side_effect=requests.exceptions.HTTPError("boom")),
            patch.object(stream, "_download_file") as mock_download,
        ):
            with pytest.raises(requests.exceptions.HTTPError):
                list(stream.read_records(sync_mode=SyncMode.full_refresh))

        mock_download.assert_not_called()

    def test_read_records_propagates_download_file_error(self, stream):
        with (
            patch.object(stream, "_trigger_export", return_value="file.csv"),
            patch.object(stream, "_download_file", side_effect=requests.exceptions.HTTPError("download failed")),
        ):
            with pytest.raises(requests.exceptions.HTTPError):
                list(stream.read_records(sync_mode=SyncMode.full_refresh))

    def test_read_records_raises_traced_config_error_when_export_resource_not_found(self, stream):
        # A 410 mid-sync (unlike during check_connection) means the export genuinely failed, so it
        # must surface as a clearly-classified, readable AirbyteTracedException in the sync logs,
        # explicitly attributed to the export-triggering step.
        with (
            patch.object(stream, "_trigger_export", side_effect=ResourceNotFoundError("Expensify resource not found.")),
            patch.object(stream, "_download_file") as mock_download,
        ):
            with pytest.raises(AirbyteTracedException) as exc_info:
                list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert exc_info.value.failure_type == FailureType.config_error
        assert "410" in exc_info.value.message
        assert "triggering the reports export" in exc_info.value.message
        mock_download.assert_not_called()

    def test_read_records_raises_traced_config_error_when_export_credentials_invalid(self, stream):
        with (
            patch.object(stream, "_trigger_export", side_effect=CredentialsInvalidError("Expensify credentials are invalid.")),
            patch.object(stream, "_download_file") as mock_download,
        ):
            with pytest.raises(AirbyteTracedException) as exc_info:
                list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert exc_info.value.failure_type == FailureType.config_error
        assert "401" in exc_info.value.message
        assert "triggering the reports export" in exc_info.value.message
        mock_download.assert_not_called()

    def test_read_records_raises_traced_config_error_when_download_resource_not_found(self, stream):
        # Distinguishes a 410 during download (e.g. an expired export file) from a 410 during
        # export triggering, so operators can tell which step actually failed from the message.
        with (
            patch.object(stream, "_trigger_export", return_value="file.csv"),
            patch.object(stream, "_download_file", side_effect=ResourceNotFoundError("Expensify resource not found.")),
        ):
            with pytest.raises(AirbyteTracedException) as exc_info:
                list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert exc_info.value.failure_type == FailureType.config_error
        assert "410" in exc_info.value.message
        assert "downloading the exported file 'file.csv'" in exc_info.value.message

    def test_read_records_raises_traced_config_error_when_download_credentials_invalid(self, stream):
        with (
            patch.object(stream, "_trigger_export", return_value="file.csv"),
            patch.object(stream, "_download_file", side_effect=CredentialsInvalidError("Expensify credentials are invalid.")),
        ):
            with pytest.raises(AirbyteTracedException) as exc_info:
                list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert exc_info.value.failure_type == FailureType.config_error
        assert "401" in exc_info.value.message
        assert "downloading the exported file 'file.csv'" in exc_info.value.message

    def test_read_records_computes_updated_at_cursor_from_date_columns(self, stream):
        csv_data = "reportID,created,submitted,approved,reimbursed\n1,2026-08-01,2026-08-02,2026-08-03,2026-08-04\n2,2026-08-10,,,\n"

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv"),
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert records[0]["updatedAt"] == "2026-08-04T00:00:00+00:00"
        assert records[1]["updatedAt"] == "2026-08-10T00:00:00+00:00"

    def test_read_records_computes_export_cursor_from_created_and_submitted_only(self, stream):
        # Unlike `updatedAt`, `createdOrSubmittedAt` must NOT be affected by approved/reimbursed.
        csv_data = "reportID,created,submitted,approved,reimbursed\n1,2026-08-01,2026-08-02,2026-08-03,2026-08-04\n2,2026-08-10,,,\n"

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv"),
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert records[0]["createdOrSubmittedAt"] == "2026-08-02T00:00:00+00:00"
        assert records[1]["createdOrSubmittedAt"] == "2026-08-10T00:00:00+00:00"

    def test_read_records_incremental_does_not_filter_records_by_updated_at(self, stream):
        # Regression test: rows must NOT be filtered out based on `updatedAt` vs. the state's
        # `updatedAt`. That state value reflects the last sync time, not the export window, so
        # filtering on it is unsafe once `start_date` is widened to backfill older data - it would
        # incorrectly skip legitimately new (but old) rows returned by the export.
        csv_data = (
            "reportID,created,submitted,approved,reimbursed\n"
            "1,2026-08-01,2026-08-01,2026-08-01,2026-08-01\n"
            "2,2026-08-10,2026-08-10,2026-08-10,2026-08-10\n"
        )
        stream_state = {"updatedAt": "2026-08-05T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # Export window resumes from the later of the two dates (config start_date already newer here).
        mock_trigger.assert_called_once_with(start_date="2026-08-30")
        assert [r["reportID"] for r in records] == ["1", "2"]

    def test_read_records_incremental_resumes_export_from_state_cursor_when_newer(self, stream):
        # Isolate the "state cursor wins over configured start_date" behavior from the lookback
        # window (covered separately below) by disabling the lookback for this test.
        stream.lookback_window_days = 0
        csv_data = "reportID,created\n1,2026-08-30\n2,2026-08-31\n"
        stream_state = {"updatedAt": "2026-08-31T00:00:00+00:00", "createdOrSubmittedAt": "2026-08-31T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # State cursor (2026-08-31) is newer than the configured start_date (2026-08-30), so it wins.
        mock_trigger.assert_called_once_with(start_date="2026-08-31")
        # All records returned by the export are yielded; the connector does not re-filter rows
        # locally based on the `updatedAt` cursor.
        assert [r["reportID"] for r in records] == ["1", "2"]

    def test_read_records_incremental_with_widened_start_date_does_not_skip_past_records(self, stream):
        # Regression test: widening `start_date` backward (to backfill older data) on a stream
        # that already has state from a previous, narrower-range sync must not cause older rows
        # to be skipped just because their `updatedAt` predates the state's `updatedAt` (which
        # reflects the previous sync's run time, not actual data freshness).
        stream.lookback_window_days = 0  # Isolate from the lookback window, covered separately below.
        stream.start_date = "2020-01-01"  # Widened far into the past.
        csv_data = "reportID,created\n1,2020-01-15\n2,2026-08-10\n"
        # State came from a previous run whose export window started later (2026-08-01) and whose
        # `updatedAt`/`createdOrSubmittedAt` reflect that narrower window, not the newly-widened one.
        stream_state = {"updatedAt": "2026-08-01T00:00:00+00:00", "createdOrSubmittedAt": "2026-08-01T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # The state's export cursor (2026-08-01) is newer than the widened start_date (2020-01-01),
        # so it still wins for resuming the export window...
        mock_trigger.assert_called_once_with(start_date="2026-08-01")
        # ...but both records returned by the export are still yielded: report 1's `created` date
        # (2020-01-15) is older than the state's `updatedAt`, yet it must not be skipped.
        assert [r["reportID"] for r in records] == ["1", "2"]

    def test_read_records_incremental_widened_start_date_still_needs_reset_beyond_lookback(self, stream):
        # Regression test: widening `start_date` further into the past than the lookback window
        # reaches does NOT retroactively backfill that older data - the connector documents that
        # a state reset (or full refresh) is still required in that case, it only guarantees that
        # recent (within-lookback) late changes aren't missed without a reset.
        stream.start_date = "2020-01-01"  # Widened far into the past, well beyond the lookback window.
        stream_state = {"updatedAt": "2026-08-31T00:00:00+00:00", "createdOrSubmittedAt": "2026-08-31T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value="reportID,created\n"),
        ):
            list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # The resumed export window only trails back by the (default 30-day) lookback window from
        # the state cursor (2026-08-31 -> 2026-08-01), NOT all the way back to the widened
        # start_date (2020-01-01). Fully backfilling from 2020-01-01 still requires a state reset.
        mock_trigger.assert_called_once_with(start_date="2026-08-01")

    def test_read_records_incremental_resumes_export_from_lookback_window_before_state_cursor(self, stream):
        # Core regression test for the lookback window: the export resumes from
        # `lookback_window_days` before the state's export cursor, not from the cursor itself, so
        # reports approved/reimbursed after their created/submitted date keep being re-exported.
        stream.lookback_window_days = 10
        stream_state = {"createdOrSubmittedAt": "2026-09-10T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value="reportID,created\n"),
        ):
            list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        mock_trigger.assert_called_once_with(start_date="2026-08-31")

    def test_read_records_incremental_lookback_window_never_precedes_configured_start_date(self, stream):
        # The lookback window must never push the export start earlier than the configured
        # `start_date`, which remains a hard lower bound.
        stream.lookback_window_days = 365
        stream_state = {"createdOrSubmittedAt": "2026-09-10T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value="reportID,created\n"),
        ):
            list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # 2026-09-10 minus 365 days is well before the configured start_date (2026-08-30), so the
        # configured start_date wins.
        mock_trigger.assert_called_once_with(start_date="2026-08-30")

    def test_read_records_incremental_replays_report_created_before_cursor_but_approved_later(self, stream):
        # End-to-end regression test: a report created before the (trailed-back) resumed export
        # window's raw cursor date, but approved later within the lookback window, must be
        # re-exported and re-synced rather than permanently dropped.
        stream.start_date = "2026-01-01"
        stream.lookback_window_days = 10
        # Previous sync's export cursor reflects a report created/submitted on 2026-09-10.
        stream_state = {"updatedAt": "2026-09-10T00:00:00+00:00", "createdOrSubmittedAt": "2026-09-10T00:00:00+00:00"}
        # This report was created on 2026-09-05 (before the raw cursor) but only approved on
        # 2026-09-12 (after the previous sync), so it must be re-exported by trailing back.
        csv_data = "reportID,created,approved\n1,2026-09-05,2026-09-12\n"

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # Lookback window (10 days) pulls the export start back to 2026-08-31, before the report's
        # created date (2026-09-05), so the report is included in the re-export.
        mock_trigger.assert_called_once_with(start_date="2026-08-31")
        assert [r["reportID"] for r in records] == ["1"]
        assert records[0]["updatedAt"] == "2026-09-12T00:00:00+00:00"

    def test_read_records_incremental_replays_report_with_later_reimbursement_after_approval(self, stream):
        # A report approved before the resumed window, but reimbursed even later, must also keep
        # being replayed within the lookback window.
        stream.start_date = "2026-01-01"
        stream.lookback_window_days = 15
        stream_state = {"updatedAt": "2026-09-10T00:00:00+00:00", "createdOrSubmittedAt": "2026-09-10T00:00:00+00:00"}
        csv_data = "reportID,created,approved,reimbursed\n1,2026-09-01,2026-09-11,2026-09-20\n"

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # Lookback window (15 days) pulls the export start back to 2026-08-26, before the report's
        # created date (2026-09-01).
        mock_trigger.assert_called_once_with(start_date="2026-08-26")
        assert [r["reportID"] for r in records] == ["1"]
        assert records[0]["updatedAt"] == "2026-09-20T00:00:00+00:00"

    def test_read_records_incremental_does_not_resume_export_from_full_updated_at_cursor(self, stream):
        # Regression test: `updatedAt` (which also reflects approved/reimbursed) must NOT be used
        # to resume the export window - only `createdOrSubmittedAt` should. Otherwise a report
        # reimbursed after the configured start/end_date window would incorrectly push the
        # resumed export window forward past reports that still need to be (re-)exported.
        csv_data = "reportID,created\n1,2026-08-30\n2,2026-08-31\n"
        stream_state = {"updatedAt": "2026-08-31T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        # No `createdOrSubmittedAt` in state, so the export window starts from the configured start_date.
        mock_trigger.assert_called_once_with(start_date="2026-08-30")

    def test_read_records_incremental_skips_export_when_resumed_export_cursor_is_past_end_date(self, stream):
        # Isolate from the lookback window (which would otherwise pull the resumed cursor back
        # before end_date) to test the "past end_date" skip guard on its own.
        stream.lookback_window_days = 0
        stream_state = {"createdOrSubmittedAt": "2026-09-05T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export") as mock_trigger,
            patch.object(stream, "_download_file") as mock_download,
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        assert records == []
        mock_trigger.assert_not_called()
        mock_download.assert_not_called()

    def test_read_records_incremental_does_not_skip_export_when_only_full_updated_at_is_past_end_date(self, stream):
        # Regression test: a report can be approved/reimbursed well after it was created/submitted,
        # pushing `updatedAt` (one of whose source fields is "reimbursed") past the configured
        # (static) end_date, even though `createdOrSubmittedAt` (created/submitted only, matching
        # Expensify's own startDate/endDate filter semantics) is still within range. Resuming
        # from `updatedAt` in that case would incorrectly skip the entire sync.
        # Report was created 2026-08-30 and previously reimbursed 2026-09-05 (hence the stale
        # `updatedAt` state below); it's now been re-reimbursed even later, on 2026-09-06.
        csv_data = "reportID,created,reimbursed\n1,2026-08-30,2026-09-06\n"
        stream_state = {"updatedAt": "2026-09-05T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        mock_trigger.assert_called_once_with(start_date="2026-08-30")
        assert [r["reportID"] for r in records] == ["1"]

    def test_read_records_full_refresh_ignores_stream_state(self, stream):
        csv_data = "reportID,created\n1,2026-08-01\n2,2026-08-10\n"
        stream_state = {"updatedAt": "2026-08-05T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="report.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh, stream_state=stream_state))

        mock_trigger.assert_called_once_with(start_date="2026-08-30")
        assert [r["reportID"] for r in records] == ["1", "2"]


class TestGetUpdatedState:
    def test_returns_max_of_current_and_latest_cursor_values(self, stream):
        current_state = {"updatedAt": "2026-08-01T00:00:00+00:00"}
        latest_record = {"reportID": "1", "updatedAt": "2026-08-05T00:00:00+00:00"}

        assert stream.get_updated_state(current_state, latest_record) == {"updatedAt": "2026-08-05T00:00:00+00:00"}

    def test_keeps_current_state_when_latest_record_cursor_is_older(self, stream):
        current_state = {"updatedAt": "2026-08-10T00:00:00+00:00"}
        latest_record = {"reportID": "1", "updatedAt": "2026-08-05T00:00:00+00:00"}

        assert stream.get_updated_state(current_state, latest_record) == {"updatedAt": "2026-08-10T00:00:00+00:00"}

    def test_handles_missing_current_state(self, stream):
        latest_record = {"reportID": "1", "updatedAt": "2026-08-05T00:00:00+00:00"}

        assert stream.get_updated_state({}, latest_record) == {"updatedAt": "2026-08-05T00:00:00+00:00"}

    def test_handles_missing_cursor_values(self, stream):
        assert stream.get_updated_state({}, {"reportID": "1", "updatedAt": None}) == {}

    def test_tracks_export_cursor_alongside_updated_at(self, stream):
        current_state = {"updatedAt": "2026-08-10T00:00:00+00:00", "createdOrSubmittedAt": "2026-08-01T00:00:00+00:00"}
        latest_record = {
            "reportID": "1",
            "updatedAt": "2026-08-15T00:00:00+00:00",  # e.g. reimbursed later
            "createdOrSubmittedAt": "2026-08-05T00:00:00+00:00",
        }

        assert stream.get_updated_state(current_state, latest_record) == {
            "updatedAt": "2026-08-15T00:00:00+00:00",
            "createdOrSubmittedAt": "2026-08-05T00:00:00+00:00",
        }

    def test_export_cursor_does_not_regress_when_latest_record_export_cursor_is_older(self, stream):
        current_state = {"updatedAt": "2026-08-10T00:00:00+00:00", "createdOrSubmittedAt": "2026-08-09T00:00:00+00:00"}
        latest_record = {"reportID": "1", "updatedAt": "2026-08-15T00:00:00+00:00", "createdOrSubmittedAt": "2026-08-01T00:00:00+00:00"}

        assert stream.get_updated_state(current_state, latest_record) == {
            "updatedAt": "2026-08-15T00:00:00+00:00",
            "createdOrSubmittedAt": "2026-08-09T00:00:00+00:00",
        }


class TestTriggerExport:
    def test_trigger_export_uses_configured_date_range(self, stream):
        with patch("source_expensify.source._post_job_description") as mock_post:
            mock_post.return_value.text = "file.csv"

            stream._trigger_export()

        job_description = mock_post.call_args.args[0]
        assert job_description["inputSettings"]["filters"] == {
            "startDate": "2026-08-30",
            "endDate": "2026-08-31",
        }


class TestPostJobDescription:
    def test_posts_json_payload_and_returns_successful_response(self):
        response = requests.Response()
        response.status_code = 200
        response._content = b"file.csv"

        with patch("source_expensify.source.requests.post", return_value=response) as mock_post:
            result = _post_job_description({"type": "download"})

        assert result is response
        mock_post.assert_called_once_with(
            "https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations",
            data={"requestJobDescription": '{"type": "download"}'},
            timeout=60,
        )

    @pytest.mark.parametrize(
        ("response_code", "exception"),
        [
            (401, CredentialsInvalidError),
            (410, ResourceNotFoundError),
            (429, RateLimitExceededError),
        ],
    )
    def test_raises_for_expensify_error_response_codes(self, response_code, exception):
        response = requests.Response()
        response.status_code = 200
        response._content = f'{{"responseCode": {response_code}}}'.encode()

        with patch("source_expensify.source.requests.post", return_value=response):
            with pytest.raises(exception):
                _post_job_description({"type": "get"})

    @patch("time.sleep", return_value=None)
    def test_raises_for_http_server_errors(self, mock_sleep, requests_mock):
        requests_mock.post(EXPENSIFY_URL, status_code=503, text="unavailable")

        with pytest.raises(requests.exceptions.HTTPError):
            _post_job_description({"type": "get"})


class TestDownloadFile:
    def test_download_file_posts_credentials_and_file_name(self, stream):
        response = requests.Response()
        response.status_code = 200
        response._content = b"reportID,amount\n1,100\n"

        with patch("source_expensify.source.requests.post", return_value=response) as mock_post:
            result = stream._download_file("report.csv")

        assert result == "reportID,amount\n1,100\n"
        job_description = json.loads(mock_post.call_args.kwargs["data"]["requestJobDescription"])
        assert job_description == {
            "type": "download",
            "credentials": {"partnerUserID": "user-id", "partnerUserSecret": "user-secret"},
            "fileName": "report.csv",
            "fileSystem": "integrationServer",
        }


class TestCheckConnection:
    def test_check_connection_accepts_valid_credentials(self):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"responseCode": 200}'
        source = SourceExpensify()
        logger = Mock()

        with patch("source_expensify.source.requests.post", return_value=response):
            result = source.check_connection(logger, {"partner_user_id": "user-id", "partner_user_secret": "user-secret"})

        assert result == (True, None)

    @pytest.mark.parametrize(
        ("response_code", "expected"),
        [
            (401, (False, None)),
            (410, (True, None)),
            (429, (False, RateLimitExceededError)),
        ],
    )
    def test_check_connection_classifies_expensify_errors(self, response_code, expected):
        response = requests.Response()
        response.status_code = 200
        response._content = f'{{"responseCode": {response_code}}}'.encode()
        source = SourceExpensify()
        logger = Mock()

        with patch("source_expensify.source.requests.post", return_value=response):
            result = source.check_connection(logger, {"partner_user_id": "user-id", "partner_user_secret": "user-secret"})

        assert result[0] is expected[0]
        if expected[1] is None:
            assert result[1] is None
        else:
            assert isinstance(result[1], expected[1])


class TestSendRequestRetries:
    @patch("time.sleep", return_value=None)
    def test_retries_on_rate_limit_with_fixed_backoff(self, mock_sleep, requests_mock):
        requests_mock.post(
            EXPENSIFY_URL,
            [
                {"status_code": 429, "json": {"responseMessage": "Too many requests. Please try again later", "responseCode": 429}},
                {"status_code": 200, "text": "ok"},
            ],
        )

        response = _send_request({"requestJobDescription": "{}"})

        assert response.text == "ok"
        assert requests_mock.call_count == 2
        mock_sleep.assert_any_call(11)  # fixed rate-limit backoff (10) + 1 extra second

    @patch("time.sleep", return_value=None)
    def test_retries_on_transient_server_error(self, mock_sleep, requests_mock):
        requests_mock.post(
            EXPENSIFY_URL,
            [
                {"status_code": 503, "text": "unavailable"},
                {"status_code": 200, "text": "ok"},
            ],
        )

        response = _send_request({"requestJobDescription": "{}"})

        assert response.text == "ok"
        assert requests_mock.call_count == 2

    @patch("time.sleep", return_value=None)
    def test_gives_up_immediately_on_permanent_client_error(self, mock_sleep, requests_mock):
        requests_mock.post(EXPENSIFY_URL, status_code=401, text="unauthorized")

        # A real HTTP-level 401 is classified the same way as Expensify's 200-with-JSON-body
        # error format, instead of surfacing as an opaque requests.HTTPError.
        with pytest.raises(CredentialsInvalidError):
            _send_request({"requestJobDescription": "{}"})

        assert requests_mock.call_count == 1

    @patch("time.sleep", return_value=None)
    def test_gives_up_immediately_on_http_level_policy_not_found(self, mock_sleep, requests_mock):
        # Regression test: an actual HTTP 410 status code (as opposed to a 200 response with a
        # JSON error body) must also be classified rather than propagating as a raw HTTPError.
        requests_mock.post(EXPENSIFY_URL, status_code=410, text="gone")

        with pytest.raises(ResourceNotFoundError):
            _send_request({"requestJobDescription": "{}"})

        assert requests_mock.call_count == 1

    @patch("time.sleep", return_value=None)
    def test_gives_up_after_max_retries_on_persistent_server_error(self, mock_sleep, requests_mock):
        requests_mock.post(EXPENSIFY_URL, status_code=500, text="server error")

        with pytest.raises(requests.exceptions.HTTPError):
            _send_request({"requestJobDescription": "{}"})

        assert requests_mock.call_count > 1


class TestStreamsLookbackWindowWiring:
    def test_streams_defaults_lookback_window_days_when_absent_from_config(self):
        source = SourceExpensify()
        config = {
            "partner_user_id": "user-id",
            "partner_user_secret": "user-secret",
            "start_date": "2026-08-30",
        }

        (reports_stream,) = source.streams(config)

        assert reports_stream.lookback_window_days == DEFAULT_LOOKBACK_WINDOW_DAYS == 30

    def test_streams_passes_through_configured_lookback_window_days(self):
        source = SourceExpensify()
        config = {
            "partner_user_id": "user-id",
            "partner_user_secret": "user-secret",
            "start_date": "2026-08-30",
            "lookback_window_days": 7,
        }

        (reports_stream,) = source.streams(config)

        assert reports_stream.lookback_window_days == 7


class TestSpecSchema:
    @pytest.fixture
    def spec_properties(self):
        spec_path = Path(__file__).parent.parent / "source_expensify" / "spec.yaml"
        spec = yaml.safe_load(spec_path.read_text())
        return spec["connectionSpecification"]["properties"]

    def test_lookback_window_days_is_optional_integer_with_default_30(self, spec_properties):
        assert "lookback_window_days" in spec_properties
        field = spec_properties["lookback_window_days"]
        assert field["type"] == "integer"
        assert field["default"] == 30
        assert "lookback_window_days" not in yaml.safe_load((Path(__file__).parent.parent / "source_expensify" / "spec.yaml").read_text())[
            "connectionSpecification"
        ].get("required", [])
