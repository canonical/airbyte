# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import logging
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from conftest import build_source, load_response

from airbyte_cdk.models import SyncMode
from airbyte_cdk.test.catalog_builder import CatalogBuilder
from airbyte_cdk.test.entrypoint_wrapper import read
from airbyte_cdk.test.state_builder import StateBuilder


THREADS_URL = "https://api.kapa.ai/query/v1/projects/d7b46c01-32a3-4f74-80d3-616a3c18fb6b/threads/"
END_USERS_URL = "https://api.kapa.ai/query/v1/projects/d7b46c01-32a3-4f74-80d3-616a3c18fb6b/end-users/"


def read_threads(config, state=None, expecting_exception=False):
    catalog = CatalogBuilder().with_stream("threads", SyncMode.incremental).build()
    state = StateBuilder().build() if state is None else state
    return read(build_source(config, state), config, catalog, state, expecting_exception)


def read_end_users(config):
    catalog = CatalogBuilder().with_stream("end_users", SyncMode.full_refresh).build()
    state = StateBuilder().build()
    return read(build_source(config, state), config, catalog, state)


def test_threads_paginates_and_emits_records(config, requests_mock):
    requests_mock.get(
        THREADS_URL,
        [
            {"json": load_response("threads_page_1.json")},
            {"json": load_response("threads_page_2.json")},
        ],
    )

    output = read_threads(config)

    assert [message.record.data["id"] for message in output.records] == [
        "6ea2745a-b70d-42f3-b13c-a4227803a4d7",
        "47edf32e-b71c-4748-ab0b-958414daca2d",
    ]
    first_record = output.records[0].record.data
    assert first_record["question_answers"][0]["end_user"]["identifier"] == "example-user"
    assert first_record["custom_tags"][0]["is_deleted"] is False
    assert first_record["interaction_tags"][0]["display_name"] == "Example interaction"
    assert first_record["integration"]["integration_type"] == "API"
    assert requests_mock.call_count == 2

    first_request, second_request = requests_mock.request_history
    first_query = parse_qs(urlparse(first_request.url).query)
    second_query = parse_qs(urlparse(second_request.url).query)

    assert first_request.headers["X-API-KEY"] == "test-api-key"
    assert first_request.headers["Accept"] == "application/json"
    assert first_query["page_size"] == ["500"]
    assert first_query["sort"] == ["asc"]
    assert first_query["include"] == ["feedback,status_tag,custom_tags,interaction_tags,end_user,integration"]
    assert "cursor" not in first_query
    assert second_query["cursor"] == ["next-page"]


def test_threads_uses_prior_state_as_inclusive_lower_bound(config, requests_mock):
    requests_mock.get(THREADS_URL, json={"results": [], "next_cursor": None})
    prior_cursor = "2024-02-01T12:30:00.000000+0000"
    state = StateBuilder().with_stream_state("threads", {"last_activity_at": prior_cursor}).build()

    read_threads(config, state)

    query = parse_qs(urlparse(requests_mock.last_request.url).query)
    actual_lower_bound = datetime.fromisoformat(query["updated_since"][0])
    assert actual_lower_bound == datetime.fromisoformat(prior_cursor)


def test_threads_discovery_exposes_nested_fields(config):
    catalog = build_source(config).discover(logger=logging.getLogger("source-kapa"), config=config)
    threads = next(stream for stream in catalog.streams if stream.name == "threads")
    properties = threads.json_schema["properties"]
    question_answer = properties["question_answers"]["items"]
    custom_tag = properties["custom_tags"]["items"]
    interaction_tag = properties["interaction_tags"]["items"]

    assert question_answer["additionalProperties"] is True
    assert question_answer["properties"]["id"] == {"type": "string", "format": "uuid"}
    assert question_answer["properties"]["created_at"]["format"] == "date-time"
    assert question_answer["properties"]["end_user"]["properties"]["identifier"] == {"type": "string"}
    assert question_answer["properties"]["feedback"]["items"]["additionalProperties"] is True
    assert custom_tag["properties"]["is_deleted"] == {"type": "boolean"}
    assert interaction_tag["properties"]["display_name"] == {"type": "string"}


def test_end_users_paginates_and_emits_records(config, requests_mock):
    requests_mock.get(
        END_USERS_URL,
        [
            {"json": load_response("end_users_page_1.json")},
            {"json": load_response("end_users_page_2.json")},
        ],
    )

    output = read_end_users(config)

    assert [message.record.data["id"] for message in output.records] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    assert requests_mock.call_count == 2

    first_request, second_request = requests_mock.request_history
    first_query = parse_qs(urlparse(first_request.url).query)
    second_query = parse_qs(urlparse(second_request.url).query)

    assert first_request.headers["X-API-KEY"] == "test-api-key"
    assert "page" not in first_query
    assert second_query["page"] == ["2"]


def test_end_users_discovery_exposes_key_and_nullable_identifiers(config):
    catalog = build_source(config).discover(logger=logging.getLogger("source-kapa"), config=config)
    end_users = next(stream for stream in catalog.streams if stream.name == "end_users")
    properties = end_users.json_schema["properties"]

    assert end_users.source_defined_primary_key == [["id"]]
    assert properties["id"] == {"type": "string", "format": "uuid"}
    assert properties["email"]["type"] == ["null", "string"]
    assert properties["company_name"]["type"] == ["null", "string"]
    assert properties["latest_activity_at"]["format"] == "date-time"
