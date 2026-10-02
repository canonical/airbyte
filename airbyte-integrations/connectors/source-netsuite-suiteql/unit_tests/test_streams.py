from requests_oauthlib import OAuth1

from source_netsuite_suiteql.streams import SuiteqlStream


def make_stream(page_size: int = 1000) -> SuiteqlStream:
    return SuiteqlStream(
        name="customers",
        query="SELECT id, email FROM customer WHERE id > ?",
        parameters=["100"],
        base_url="https://12345.suitetalk.api.netsuite.com",
        page_size=page_size,
        auth=OAuth1("key", "secret", "token", "token-secret"),
    )


def test_read_records_posts_query_and_paginates(requests_mock) -> None:
    endpoint = "https://12345.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
    requests_mock.post(
        endpoint,
        [
            {"json": {"items": [{"id": "101"}], "count": 1, "offset": 0, "hasMore": True}},
            {"json": {"items": [{"id": "102"}], "count": 1, "offset": 1, "hasMore": False}},
        ],
    )

    records = list(make_stream(page_size=1).read_records(sync_mode=None))

    assert records == [{"id": "101"}, {"id": "102"}]
    assert [request.qs for request in requests_mock.request_history] == [
        {"limit": ["1"], "offset": ["0"]},
        {"limit": ["1"], "offset": ["1"]},
    ]
    assert requests_mock.request_history[0].json() == {
        "q": "SELECT id, email FROM customer WHERE id > ?",
        "params": ["100"],
    }
    assert requests_mock.request_history[0].headers["Prefer"].decode() == "transient"


def test_get_json_schema_infers_sampled_fields(requests_mock) -> None:
    endpoint = "https://12345.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
    requests_mock.post(endpoint, json={"items": [{"id": "101", "active": True, "amount": 12.5}]})

    schema = make_stream().get_json_schema()

    assert schema["properties"] == {
        "id": {"type": ["null", "string"]},
        "active": {"type": ["null", "boolean"]},
        "amount": {"type": ["null", "number"]},
    }
    assert requests_mock.last_request.qs == {"limit": ["1"], "offset": ["0"]}