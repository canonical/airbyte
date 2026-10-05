# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import json
from pathlib import Path
from unittest.mock import Mock

from source_netsuite_suiteql.source import SourceNetsuiteSuiteql

from airbyte_cdk.models import (
    AirbyteStateBlob,
    AirbyteStateMessage,
    AirbyteStateType,
    AirbyteStream,
    AirbyteStreamState,
    ConfiguredAirbyteCatalog,
    ConfiguredAirbyteStream,
    DestinationSyncMode,
    StreamDescriptor,
    SyncMode,
)
from airbyte_cdk.test.entrypoint_wrapper import discover, read


INTEGRATION_TESTS_DIR = Path(__file__).parent
ENDPOINT = "https://12345-sb1.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"


def load_json(file_name: str):
    return json.loads((INTEGRATION_TESTS_DIR / file_name).read_text())


def load_expected_records():
    return [json.loads(line) for line in (INTEGRATION_TESTS_DIR / "expected_records.jsonl").read_text().splitlines()]


def configured_catalog() -> ConfiguredAirbyteCatalog:
    return ConfiguredAirbyteCatalog(
        streams=[
            ConfiguredAirbyteStream(
                stream=AirbyteStream(name="transaction", json_schema={}, supported_sync_modes=[SyncMode.full_refresh]),
                sync_mode=SyncMode.full_refresh,
                destination_sync_mode=DestinationSyncMode.append,
            )
        ]
    )


def configured_incremental_catalog() -> ConfiguredAirbyteCatalog:
    return ConfiguredAirbyteCatalog(
        streams=[
            ConfiguredAirbyteStream(
                stream=AirbyteStream(
                    name="transaction",
                    json_schema={},
                    supported_sync_modes=[SyncMode.full_refresh, SyncMode.incremental],
                    source_defined_cursor=True,
                    default_cursor_field=["cursor_ts"],
                    source_defined_primary_key=[["id"]],
                ),
                sync_mode=SyncMode.incremental,
                cursor_field=["cursor_ts"],
                primary_key=[["id"]],
                destination_sync_mode=DestinationSyncMode.append_dedup,
            )
        ]
    )


def test_check_succeeds_with_valid_config(requests_mock) -> None:
    requests_mock.post(ENDPOINT, json={"items": [{"id": "101"}], "count": 1, "offset": 0, "hasMore": False})

    is_available, error = SourceNetsuiteSuiteql().check_connection(logger=Mock(), config=load_json("sample_config.json"))

    assert is_available is True
    assert error is None
    assert requests_mock.last_request.json() == {
        "q": ("SELECT *, TO_CHAR(lastmodifiedat, 'YYYY-MM-DD HH24:MI:SS') AS cursor_ts " "FROM transaction ORDER BY cursor_ts, id")
    }


def test_check_fails_with_invalid_credentials(requests_mock) -> None:
    requests_mock.post(ENDPOINT, status_code=401, json={"type": "https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.2"})

    is_available, error = SourceNetsuiteSuiteql().check_connection(logger=Mock(), config=load_json("invalid_config.json"))

    assert is_available is False
    assert error is not None


def test_discover_infers_a_full_refresh_stream(requests_mock) -> None:
    requests_mock.post(
        ENDPOINT,
        json={
            "items": [{"id": "101", "lastmodifiedat": "2024-06-01T12:00:00Z", "cursor_ts": "2024-06-01 12:00:00"}],
            "count": 1,
            "offset": 0,
            "hasMore": False,
        },
    )

    output = discover(SourceNetsuiteSuiteql(), load_json("sample_config.json"))

    stream = output.catalog.catalog.streams[0]
    assert stream.name == "transaction"
    assert stream.supported_sync_modes == [SyncMode.full_refresh, SyncMode.incremental]
    assert stream.json_schema["properties"] == {
        "id": {"type": ["null", "string"]},
        "lastmodifiedat": {"type": ["null", "string"]},
        "cursor_ts": {"type": ["null", "string"]},
    }
    assert requests_mock.last_request.qs == {"limit": ["100"], "offset": ["0"]}


def test_read_emits_records_across_pages(requests_mock) -> None:
    requests_mock.post(
        ENDPOINT,
        [
            {
                "json": {
                    "items": [{"id": "101", "lastmodifiedat": "2024-06-01T12:00:00Z", "cursor_ts": "2024-06-01 12:00:00"}],
                    "count": 1,
                    "offset": 0,
                    "hasMore": False,
                }
            },
            {
                "json": {
                    "items": [{"id": "101", "lastmodifiedat": "2024-06-01T12:00:00Z", "cursor_ts": "2024-06-01 12:00:00"}],
                    "count": 1,
                    "offset": 0,
                    "hasMore": True,
                }
            },
            {
                "json": {
                    "items": [{"id": "101", "lastmodifiedat": "2024-06-01T12:00:00Z", "cursor_ts": "2024-06-01 12:00:00"}],
                    "count": 1,
                    "offset": 0,
                    "hasMore": False,
                }
            },
            {
                "json": {
                    "items": [{"id": "102", "lastmodifiedat": "2024-06-02T12:00:00Z", "cursor_ts": "2024-06-02 12:00:00"}],
                    "count": 1,
                    "offset": 1,
                    "hasMore": False,
                }
            },
        ],
    )
    output = read(SourceNetsuiteSuiteql(), load_json("sample_config.json"), configured_catalog())

    assert [message.record.data for message in output.records] == load_expected_records()
    assert [request.qs for request in requests_mock.request_history] == [
        {"limit": ["1"], "offset": ["0"]},
        {"limit": ["1"], "offset": ["0"]},
        {"limit": ["100"], "offset": ["0"]},
        {"limit": ["1"], "offset": ["1"]},
    ]


def test_incremental_read_uses_state_and_emits_updated_state(requests_mock) -> None:
    config = load_json("sample_config.json")
    state = [
        AirbyteStateMessage(
            type=AirbyteStateType.STREAM,
            stream=AirbyteStreamState(
                stream_descriptor=StreamDescriptor(name="transaction", namespace=None),
                stream_state=AirbyteStateBlob(cursor_ts="2024-06-02 00:00:00"),
            ),
        )
    ]
    requests_mock.post(
        ENDPOINT,
        json={
            "items": [{"id": "103", "lastmodifiedat": "2024-06-03T00:00:00Z", "cursor_ts": "2024-06-03 00:00:00"}],
            "count": 1,
            "offset": 0,
            "hasMore": False,
        },
    )

    output = read(SourceNetsuiteSuiteql(), config, configured_incremental_catalog(), state=state)

    assert [message.record.data for message in output.records] == [
        {"id": "103", "lastmodifiedat": "2024-06-03T00:00:00Z", "cursor_ts": "2024-06-03 00:00:00"}
    ]
    assert any(request.json().get("params") == ["2024-06-02 00:00:00"] for request in requests_mock.request_history)
    assert output.state_messages[-1].state.stream.stream_state == AirbyteStateBlob(cursor_ts="2024-06-03 00:00:00")
