# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

from unittest.mock import patch

import pytest
import requests
from source_expensify.source import EXPENSIFY_URL, ExpensifyReports, _send_request

from airbyte_cdk.models import SyncMode


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

        mock_trigger.assert_called_once_with()
        mock_download.assert_called_once_with("report.csv")

        assert records == [
            {"reportID": "1", "amount": "100"},
            {"reportID": "2", "amount": "200"},
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

        def trigger_export():
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
        assert records == [{"reportID": "1", "amount": "50"}]

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


class TestSendRequestRetries:
    @patch("time.sleep", return_value=None)
    def test_retries_on_rate_limit_and_honors_retry_after(self, mock_sleep, requests_mock):
        requests_mock.post(
            EXPENSIFY_URL,
            [
                {"status_code": 429, "headers": {"Retry-After": "2"}, "text": "rate limited"},
                {"status_code": 200, "text": "ok"},
            ],
        )

        response = _send_request({"requestJobDescription": "{}"})

        assert response.text == "ok"
        assert requests_mock.call_count == 2
        mock_sleep.assert_any_call(3)  # Retry-After (2) + 1 extra second

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

        with pytest.raises(requests.exceptions.HTTPError):
            _send_request({"requestJobDescription": "{}"})

        assert requests_mock.call_count == 1

    @patch("time.sleep", return_value=None)
    def test_gives_up_after_max_retries_on_persistent_server_error(self, mock_sleep, requests_mock):
        requests_mock.post(EXPENSIFY_URL, status_code=500, text="server error")

        with pytest.raises(requests.exceptions.HTTPError):
            _send_request({"requestJobDescription": "{}"})

        assert requests_mock.call_count > 1
