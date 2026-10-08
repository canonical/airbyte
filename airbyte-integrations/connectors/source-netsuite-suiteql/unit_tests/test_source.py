# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import pytest
from source_netsuite_suiteql.errors import (
    DuplicateTableNameError,
    InvalidIdentifierError,
    MissingCatalogCursorFieldError,
    MultipleCatalogFieldsError,
    NestedCatalogFieldError,
)
from source_netsuite_suiteql.source import SourceNetsuiteSuiteql
from source_netsuite_suiteql.validation import SuiteQLCatalogStreamValidator

from airbyte_cdk.models import AirbyteStream, ConfiguredAirbyteCatalog, ConfiguredAirbyteStream, DestinationSyncMode, SyncMode


CONFIG = {
    "realm": "12345_SB1",
    "consumer_key": "consumer-key",
    "consumer_secret": "consumer-secret",
    "token_key": "token-key",
    "token_secret": "token-secret",
    "tables": [
        {
            "table_name": "transaction",
        }
    ],
}


def test_streams_build_named_query_stream() -> None:
    stream = SourceNetsuiteSuiteql().streams(CONFIG)[0]

    assert stream.name == "transaction"
    assert stream.url_base == "https://12345-sb1.suitetalk.api.netsuite.com"
    assert stream.cursor_field == []
    assert stream.supports_incremental
    assert not stream.is_resumable
    assert stream.request_body_json() == {"q": "SELECT * FROM transaction"}


@pytest.mark.parametrize(
    "table",
    [
        {"table_name": "contains spaces"},
        {"table_name": "1_starts_with_number"},
        {"table_name": "contains-hyphen"},
    ],
)
def test_streams_reject_invalid_identifiers(table: dict) -> None:
    config = {**CONFIG, "tables": [table]}

    with pytest.raises(InvalidIdentifierError, match="Table names, primary keys, and cursor fields must"):
        SourceNetsuiteSuiteql().streams(config)


def test_streams_reject_duplicate_names() -> None:
    config = {**CONFIG, "tables": [CONFIG["tables"][0], CONFIG["tables"][0]]}

    with pytest.raises(DuplicateTableNameError, match="Duplicate table names: transaction"):
        SourceNetsuiteSuiteql().streams(config)


def test_stream_is_configured_from_the_catalog() -> None:
    catalog = ConfiguredAirbyteCatalog(
        streams=[
            ConfiguredAirbyteStream(
                stream=AirbyteStream(name="transaction", json_schema={}, supported_sync_modes=[SyncMode.incremental]),
                sync_mode=SyncMode.incremental,
                destination_sync_mode=DestinationSyncMode.append_dedup,
                primary_key=[["id"]],
                cursor_field=["lastmodifiedat"],
            )
        ]
    )

    assert SuiteQLCatalogStreamValidator(catalog.streams[0]).table_fields() == {
        "primary_key": ["id"],
        "cursor_field": "lastmodifiedat",
    }


@pytest.mark.parametrize(
    ("primary_key", "cursor_field", "invalid_identifier"),
    [
        ([["id; DROP TABLE transaction"]], ["lastmodifiedat"], "id; DROP TABLE transaction"),
        ([["id"]], ["lastmodifiedat DESC"], "lastmodifiedat DESC"),
    ],
)
def test_catalog_rejects_invalid_identifiers(
    primary_key: list[list[str]],
    cursor_field: list[str],
    invalid_identifier: str,
) -> None:
    configured_stream = ConfiguredAirbyteStream(
        stream=AirbyteStream(name="transaction", json_schema={}, supported_sync_modes=[SyncMode.incremental]),
        sync_mode=SyncMode.incremental,
        destination_sync_mode=DestinationSyncMode.append_dedup,
        primary_key=primary_key,
        cursor_field=cursor_field,
    )

    with pytest.raises(InvalidIdentifierError, match=invalid_identifier):
        SuiteQLCatalogStreamValidator(configured_stream).table_fields()


def test_catalog_requires_cursor_for_incremental_streams() -> None:
    configured_stream = ConfiguredAirbyteStream(
        stream=AirbyteStream(name="transaction", json_schema={}, supported_sync_modes=[SyncMode.incremental]),
        sync_mode=SyncMode.incremental,
        destination_sync_mode=DestinationSyncMode.append,
    )

    with pytest.raises(MissingCatalogCursorFieldError, match="transaction"):
        SuiteQLCatalogStreamValidator(configured_stream).table_fields()


def test_catalog_rejects_nested_primary_keys() -> None:
    configured_stream = ConfiguredAirbyteStream(
        stream=AirbyteStream(name="transaction", json_schema={}, supported_sync_modes=[SyncMode.incremental]),
        sync_mode=SyncMode.incremental,
        destination_sync_mode=DestinationSyncMode.append_dedup,
        primary_key=[["metadata", "id"]],
        cursor_field=["lastmodifiedat"],
    )

    with pytest.raises(NestedCatalogFieldError, match="primary key"):
        SuiteQLCatalogStreamValidator(configured_stream).table_fields()


def test_catalog_rejects_multiple_cursor_fields() -> None:
    configured_stream = ConfiguredAirbyteStream(
        stream=AirbyteStream(name="transaction", json_schema={}, supported_sync_modes=[SyncMode.incremental]),
        sync_mode=SyncMode.incremental,
        destination_sync_mode=DestinationSyncMode.append,
        cursor_field=["lastmodifiedat", "createdat"],
    )

    with pytest.raises(MultipleCatalogFieldsError, match="cursor field"):
        SuiteQLCatalogStreamValidator(configured_stream).table_fields()
