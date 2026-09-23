# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

from unittest.mock import patch

import pytest
from freezegun import freeze_time
from source_expensify.expenses import ExpensifyExpensesStream
from source_expensify.source import SourceExpensify

from airbyte_cdk.models import SyncMode


@pytest.fixture
def stream():
    return ExpensifyExpensesStream(
        name="expenses",
        partner_user_id="user-id",
        partner_user_secret="user-secret",
        start_date="2026-08-30",
        end_date="2026-08-31",
    )


class TestStreamConfiguration:
    def test_stream_declares_expected_wiring(self, stream):
        assert stream.name == "expenses"
        assert stream.primary_key == "transactionID"
        assert stream.cursor_field == "updatedAt"
        assert stream.cursor_source_fields == (
            "created",
            "modifiedCreated",
            "inserted",
            "reportSubmitted",
            "reportApproved",
            "reportReimbursed",
        )
        assert stream.export_cursor_field == "createdAt"
        assert stream.export_filter_source_fields == ("created",)
        assert stream.export_type == "combinedReportData"
        assert stream.export_template_path == "templates/expenses_export_template.ftl"


class TestReadRecords:
    def test_read_records_yields_parsed_csv_rows(self, stream):
        csv_data = "reportID,transactionID,amount\n1,10,100\n1,11,200\n"

        with (
            patch.object(stream, "_trigger_export", return_value="expenses.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data) as mock_download,
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        mock_trigger.assert_called_once_with(start_date="2026-08-30")
        mock_download.assert_called_once_with("expenses.csv")

        assert records == [
            {"reportID": "1", "transactionID": "10", "amount": "100", "updatedAt": None, "createdAt": None},
            {"reportID": "1", "transactionID": "11", "amount": "200", "updatedAt": None, "createdAt": None},
        ]

    def test_read_records_no_rows(self, stream):
        csv_data = "reportID,transactionID,amount\n"

        with (
            patch.object(stream, "_trigger_export", return_value="empty.csv"),
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert records == []

    def test_read_records_computes_updated_at_cursor_from_date_columns(self, stream):
        csv_data = "transactionID,created,modifiedCreated,inserted\n" "1,2026-08-01,2026-08-02,2026-08-03\n" "2,2026-08-10,,\n"

        with (
            patch.object(stream, "_trigger_export", return_value="expenses.csv"),
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert records[0]["updatedAt"] == "2026-08-03T00:00:00+00:00"
        assert records[1]["updatedAt"] == "2026-08-10T00:00:00+00:00"

    def test_read_records_computes_updated_at_cursor_from_parent_report_date_columns(self, stream):
        # An expense's own created/modifiedCreated/inserted don't change when its parent report
        # later transitions state, so reportSubmitted/reportApproved/reportReimbursed must also
        # feed the updatedAt cursor.
        csv_data = (
            "transactionID,created,reportSubmitted,reportApproved,reportReimbursed\n" "1,2026-08-01,2026-08-02,2026-08-03,2026-08-04\n"
        )

        with (
            patch.object(stream, "_trigger_export", return_value="expenses.csv"),
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert records[0]["updatedAt"] == "2026-08-04T00:00:00+00:00"

    def test_read_records_computes_export_cursor_from_created_only(self, stream):
        # Unlike `updatedAt`, `createdAt` must NOT be affected by modifiedCreated/inserted.
        csv_data = "transactionID,created,modifiedCreated,inserted\n1,2026-08-01,2026-08-02,2026-08-03\n"

        with (
            patch.object(stream, "_trigger_export", return_value="expenses.csv"),
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.full_refresh))

        assert records[0]["createdAt"] == "2026-08-01T00:00:00+00:00"

    def test_read_records_incremental_resumes_export_from_state_cursor_when_newer(self, stream):
        stream.lookback_window_days = 0
        csv_data = "transactionID,created\n1,2026-08-30\n2,2026-08-31\n"
        stream_state = {"updatedAt": "2026-08-31T00:00:00+00:00", "createdAt": "2026-08-31T00:00:00+00:00"}

        with (
            patch.object(stream, "_trigger_export", return_value="expenses.csv") as mock_trigger,
            patch.object(stream, "_download_file", return_value=csv_data),
        ):
            records = list(stream.read_records(sync_mode=SyncMode.incremental, stream_state=stream_state))

        mock_trigger.assert_called_once_with(start_date="2026-08-31")
        assert [r["transactionID"] for r in records] == ["1", "2"]


class TestGetUpdatedState:
    def test_tracks_export_cursor_alongside_updated_at(self, stream):
        current_state = {"updatedAt": "2026-08-10T00:00:00+00:00", "createdAt": "2026-08-01T00:00:00+00:00"}
        latest_record = {
            "transactionID": "1",
            "updatedAt": "2026-08-15T00:00:00+00:00",
            "createdAt": "2026-08-05T00:00:00+00:00",
        }

        assert stream.get_updated_state(current_state, latest_record) == {
            "updatedAt": "2026-08-15T00:00:00+00:00",
            "createdAt": "2026-08-05T00:00:00+00:00",
        }


class TestTriggerExport:
    def test_trigger_export_uses_configured_date_range_and_expenses_template(self, stream):
        with patch("source_expensify.base_stream._post_job_description") as mock_post:
            mock_post.return_value.text = "file.csv"

            stream._trigger_export()

        job_description = mock_post.call_args.args[0]
        assert job_description["inputSettings"]["type"] == "combinedReportData"
        assert job_description["inputSettings"]["filters"] == {
            "startDate": "2026-08-30",
            "endDate": "2026-08-31",
        }
        template = mock_post.call_args.kwargs.get("template")
        assert "reportID" in template and "transactionID" in template
        assert "reportSubmitted" in template and "reportApproved" in template and "reportReimbursed" in template

    @freeze_time("2026-09-15 12:00:00")
    def test_omitted_end_date_defaults_to_current_date(self):
        stream = ExpensifyExpensesStream(
            name="expenses",
            partner_user_id="user-id",
            partner_user_secret="user-secret",
            start_date="2026-08-30",
        )
        assert stream.end_date == "2026-09-15"


class TestStreamsWiring:
    def test_streams_includes_expenses_stream(self):
        source = SourceExpensify()
        config = {
            "partner_user_id": "user-id",
            "partner_user_secret": "user-secret",
            "start_date": "2026-08-30",
        }

        streams = source.streams(config)

        assert [s.name for s in streams] == ["reports", "expenses"]
        expenses_stream = streams[1]
        assert isinstance(expenses_stream, ExpensifyExpensesStream)
        assert expenses_stream.primary_key == "transactionID"
