# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import pytest
from source_netsuite_suiteql.errors import (
    DuplicateQueryNameError,
    IncompleteIncrementalConfigurationError,
    InvalidCursorParameterIndexError,
    InvalidQueryNameError,
)
from source_netsuite_suiteql.source import SourceNetsuiteSuiteql


CONFIG = {
    "realm": "12345_SB1",
    "consumer_key": "consumer-key",
    "consumer_secret": "consumer-secret",
    "token_key": "token-key",
    "token_secret": "token-secret",
    "queries": [{"name": "customers", "query": "SELECT id, lastmodifiedat FROM transaction"}],
}


def test_streams_build_named_query_stream() -> None:
    stream = SourceNetsuiteSuiteql().streams(CONFIG)[0]

    assert stream.name == "customers"
    assert stream.url_base == "https://12345-sb1.suitetalk.api.netsuite.com"
    assert stream.cursor_field == []
    assert not stream.supports_incremental
    assert not stream.is_resumable
    assert stream.request_body_json() == {"q": "SELECT id, lastmodifiedat FROM transaction"}


@pytest.mark.parametrize("name", ["contains spaces", "1_starts_with_number", "contains-hyphen"])
def test_streams_reject_invalid_stream_names(name: str) -> None:
    config = {**CONFIG, "queries": [{"name": name, "query": "SELECT id FROM transaction"}]}

    with pytest.raises(InvalidQueryNameError, match="Query names must"):
        SourceNetsuiteSuiteql().streams(config)


def test_streams_reject_duplicate_names() -> None:
    config = {**CONFIG, "queries": [CONFIG["queries"][0], CONFIG["queries"][0]]}

    with pytest.raises(DuplicateQueryNameError, match="Duplicate query names: customers"):
        SourceNetsuiteSuiteql().streams(config)


@pytest.mark.parametrize(
    ("query", "error"),
    [
        (
            {"name": "customers", "query": "SELECT id FROM transaction", "primary_key": ["id"]},
            IncompleteIncrementalConfigurationError,
        ),
        (
            {
                "name": "customers",
                "query": "SELECT id FROM transaction WHERE lastmodifieddate >= ?",
                "primary_key": ["id"],
                "cursor_field": "lastmodifieddate",
                "cursor_parameter_index": 0,
            },
            InvalidCursorParameterIndexError,
        ),
    ],
)
def test_streams_reject_incomplete_or_invalid_incremental_configuration(query: dict, error: type[ValueError]) -> None:
    config = {**CONFIG, "queries": [query]}

    with pytest.raises(error, match="Incremental query 'customers'"):
        SourceNetsuiteSuiteql().streams(config)
