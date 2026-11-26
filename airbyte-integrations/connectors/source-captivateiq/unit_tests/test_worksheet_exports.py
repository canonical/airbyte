# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""Offline tests for the worksheet bulk-export streams.

They run the real manifest against mocked HTTP responses for the whole
asynchronous flow: create the export job, poll it, download the CSV file.
"""

from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests_mock
import yaml
from components import NestRecordUnderData

from airbyte_cdk.models import ConfiguredAirbyteCatalog, SyncMode
from airbyte_cdk.sources.declarative.concurrent_declarative_source import ConcurrentDeclarativeSource
from airbyte_cdk.test.catalog_builder import CatalogBuilder
from airbyte_cdk.test.entrypoint_wrapper import read


MANIFEST = yaml.safe_load((Path(__file__).resolve().parent.parent / "manifest.yaml").read_text())
CONFIG = {"api_token": "test-token", "start_date": "2024-01-01"}
API = "https://api.captivateiq.com/ciq/v1"
DOWNLOAD_URL = "https://ciq-downloads.s3.amazonaws.com/downloads/v1/abc/export.csv?Signature=sig&Expires=1"
CSV_BODY = "Unique ID,Amount,Renewal/Growth\nu-1,10.5,Growth\nu-2,,Renewal\n"


def _catalog(stream: str) -> ConfiguredAirbyteCatalog:
    return CatalogBuilder().with_stream(stream, SyncMode.full_refresh).build()


def _read(stream: str):
    catalog = _catalog(stream)
    source = ConcurrentDeclarativeSource(catalog=catalog, config=CONFIG, state=None, source_config=MANIFEST)
    return read(source, CONFIG, catalog)


def _mock_export(m: requests_mock.Mocker, list_path: str, export_path: str, final_status: str = "SUCCESS") -> None:
    m.get(f"{API}/{list_path}", json={"object": "list", "data": [{"id": "ws-1", "name": "Total Bookings"}]})
    m.post(
        f"{API}/{export_path}",
        status_code=202,
        json={"object": "job", "id": "job-1", "url": "/ciq/v1/jobs/job-1/", "status": "PENDING", "details": {}},
    )
    details: Dict[str, Any] = {"download_id": "d-1", "download_url": DOWNLOAD_URL} if final_status == "SUCCESS" else {}
    m.get(f"{API}/jobs/job-1/", json={"object": "job", "id": "job-1", "status": final_status, "details": details})
    m.get(DOWNLOAD_URL, text=CSV_BODY)


EXPECTED_RECORDS: List[Dict[str, Any]] = [
    {
        "data": {"Unique ID": "u-1", "Amount": "10.5", "Renewal/Growth": "Growth"},
        "parent_id": "ws-1",
    },
    {
        "data": {"Unique ID": "u-2", "Amount": "", "Renewal/Growth": "Renewal"},
        "parent_id": "ws-1",
    },
]


@pytest.mark.parametrize(
    "stream, list_path, export_path",
    [
        ("data-worksheet-records-export", "data-worksheets", "data-worksheets/ws-1/records/export/"),
        (
            "transformation-worksheet-records-export",
            "transformation-worksheets",
            "transformation-worksheets/ws-1/records/export/",
        ),
    ],
)
def test_export_stream_reads_all_columns(stream: str, list_path: str, export_path: str) -> None:
    with requests_mock.Mocker() as m:
        _mock_export(m, list_path, export_path)
        output = _read(stream)

        assert not output.errors, output.errors
        assert [r.record.data for r in output.records] == EXPECTED_RECORDS

        export_request = next(r for r in m.request_history if r.method == "POST")
        assert export_request.qs == {"export_format": ["csv"]}
        assert export_request.headers["Authorization"] == "Token test-token"

        # The download link is a pre-signed S3 URL: sending the API token with it
        # would leak the token to S3 and can make S3 reject the request.
        download_request = next(r for r in m.request_history if r.url == DOWNLOAD_URL)
        assert "Authorization" not in download_request.headers


def test_download_uses_link_fetched_right_before_download() -> None:
    """Links expire ~10 minutes after they are issued, and jobs can finish well
    before they are downloaded, so the link seen while polling must not be used."""
    expired_url = "https://ciq-downloads.s3.amazonaws.com/downloads/v1/abc/export.csv?Signature=old&Expires=0"
    with requests_mock.Mocker() as m:
        _mock_export(m, "data-worksheets", "data-worksheets/ws-1/records/export/")
        m.get(
            f"{API}/jobs/job-1/",
            [
                {"json": {"id": "job-1", "status": "SUCCESS", "details": {"download_url": expired_url}}},
                {"json": {"id": "job-1", "status": "SUCCESS", "details": {"download_url": DOWNLOAD_URL}}},
            ],
        )
        m.get(expired_url, status_code=403, text="<Error><Code>AccessDenied</Code></Error>")
        output = _read("data-worksheet-records-export")

        assert not output.errors, output.errors
        assert [r.record.data for r in output.records] == EXPECTED_RECORDS
        assert not any(r.url == expired_url for r in m.request_history)


@pytest.mark.parametrize("status", ["FAILURE", "REVOKED", "REJECTED", "IGNORED"])
def test_failed_export_job_is_reported(status: str) -> None:
    with requests_mock.Mocker() as m:
        _mock_export(m, "data-worksheets", "data-worksheets/ws-1/records/export/", final_status=status)
        output = _read("data-worksheet-records-export")

        assert not output.records
        assert output.errors


def test_nest_record_under_data_moves_every_column() -> None:
    record = {"Unique ID": "u-1", "data": "a column literally named data", "Amount": None}
    NestRecordUnderData().transform(record)
    assert record == {"data": {"Unique ID": "u-1", "data": "a column literally named data", "Amount": None}}
