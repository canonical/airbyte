import pytest

from source_netsuite_suiteql.errors import DuplicateQueryNameError, InvalidQueryNameError
from source_netsuite_suiteql.source import SourceNetsuiteSuiteql


CONFIG = {
    "realm": "12345_SB1",
    "consumer_key": "consumer-key",
    "consumer_secret": "consumer-secret",
    "token_key": "token-key",
    "token_secret": "token-secret",
    "queries": [{"name": "customers", "query": "SELECT id, email FROM customer"}],
}


def test_streams_build_named_query_stream() -> None:
    stream = SourceNetsuiteSuiteql().streams(CONFIG)[0]

    assert stream.name == "customers"
    assert stream.url_base == "https://12345-sb1.suitetalk.api.netsuite.com"
    assert stream.request_body_json() == {"q": "SELECT id, email FROM customer"}


@pytest.mark.parametrize("name", ["contains spaces", "1_starts_with_number", "contains-hyphen"])
def test_streams_reject_invalid_stream_names(name: str) -> None:
    config = {**CONFIG, "queries": [{"name": name, "query": "SELECT id FROM customer"}]}

    with pytest.raises(InvalidQueryNameError, match="Query names must"):
        SourceNetsuiteSuiteql().streams(config)


def test_streams_reject_duplicate_names() -> None:
    config = {**CONFIG, "queries": [CONFIG["queries"][0], CONFIG["queries"][0]]}

    with pytest.raises(DuplicateQueryNameError, match="Duplicate query names: customers"):
        SourceNetsuiteSuiteql().streams(config)