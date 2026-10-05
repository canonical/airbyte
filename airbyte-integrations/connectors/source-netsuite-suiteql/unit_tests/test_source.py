# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import pytest
from source_netsuite_suiteql.errors import (
    DuplicateTableNameError,
    InvalidIdentifierError,
)
from source_netsuite_suiteql.source import SourceNetsuiteSuiteql


CONFIG = {
    "realm": "12345_SB1",
    "consumer_key": "consumer-key",
    "consumer_secret": "consumer-secret",
    "token_key": "token-key",
    "token_secret": "token-secret",
    "tables": [
        {
            "table_name": "transaction",
            "primary_key": ["id"],
            "cursor_field": "lastmodifiedat",
        }
    ],
}


def test_streams_build_named_query_stream() -> None:
    stream = SourceNetsuiteSuiteql().streams(CONFIG)[0]

    assert stream.name == "transaction"
    assert stream.url_base == "https://12345-sb1.suitetalk.api.netsuite.com"
    assert stream.cursor_field == "cursor_ts"
    assert stream.supports_incremental
    assert stream.is_resumable
    assert stream.request_body_json() == {
        "q": (
            "SELECT *, TO_CHAR(lastmodifiedat, 'YYYY-MM-DD HH24:MI:SS') AS cursor_ts "
            "FROM transaction ORDER BY cursor_ts, id"
        )
    }


@pytest.mark.parametrize("name", ["contains spaces", "1_starts_with_number", "contains-hyphen"])
def test_streams_reject_invalid_identifiers(name: str) -> None:
    config = {**CONFIG, "tables": [{"table_name": name, "primary_key": ["id"], "cursor_field": "lastmodifiedat"}]}

    with pytest.raises(InvalidIdentifierError, match="Table names, primary keys, and cursor fields must"):
        SourceNetsuiteSuiteql().streams(config)


def test_streams_reject_duplicate_names() -> None:
    config = {**CONFIG, "tables": [CONFIG["tables"][0], CONFIG["tables"][0]]}

    with pytest.raises(DuplicateTableNameError, match="Duplicate table names: transaction"):
        SourceNetsuiteSuiteql().streams(config)
