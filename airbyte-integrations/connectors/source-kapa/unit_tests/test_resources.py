# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import logging
from urllib.parse import parse_qs, urlparse

from conftest import build_source, load_response

from airbyte_cdk.models import SyncMode
from airbyte_cdk.test.catalog_builder import CatalogBuilder
from airbyte_cdk.test.entrypoint_wrapper import read
from airbyte_cdk.test.state_builder import StateBuilder


PROJECT_ID = "d7b46c01-32a3-4f74-80d3-616a3c18fb6b"
BASE_URL = "https://api.kapa.ai"
INTEGRATIONS_URL = f"{BASE_URL}/query/v1/projects/{PROJECT_ID}/integrations/"
SOURCE_GROUPS_URL = f"{BASE_URL}/ingestion/v1/projects/{PROJECT_ID}/source-groups/"
SOURCES_URL = f"{BASE_URL}/ingestion/v1/projects/{PROJECT_ID}/sources/"


def read_stream(config, stream_name):
    catalog = CatalogBuilder().with_stream(stream_name, SyncMode.full_refresh).build()
    state = StateBuilder().build()
    return read(build_source(config, state), config, catalog, state)


def test_integrations_emit_direct_array(config, requests_mock):
    requests_mock.get(INTEGRATIONS_URL, json=load_response("integrations.json"))

    output = read_stream(config, "integrations")

    assert [message.record.data["id"] for message in output.records] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    assert output.records[1].record.data["integration_type"] == "WIDGET"
    assert requests_mock.last_request.headers["X-API-KEY"] == "test-api-key"


def test_source_groups_paginate_and_preserve_nested_groups(config, requests_mock):
    requests_mock.get(
        SOURCE_GROUPS_URL,
        [
            {"json": load_response("source_groups_page_1.json")},
            {"json": load_response("source_groups_page_2.json")},
        ],
    )

    output = read_stream(config, "source_groups")

    assert [message.record.data["id"] for message in output.records] == [
        "33333333-3333-4333-8333-333333333333",
        "55555555-5555-4555-8555-555555555555",
    ]
    assert output.records[0].record.data["sub_groups"][0]["type"] == "version"
    assert requests_mock.call_count == 2
    assert "page" not in parse_qs(urlparse(requests_mock.request_history[0].url).query)
    assert parse_qs(urlparse(requests_mock.request_history[1].url).query)["page"] == ["2"]


def test_sources_paginate_and_emit_documented_fields(config, requests_mock):
    requests_mock.get(
        SOURCES_URL,
        [
            {"json": load_response("sources_page_1.json")},
            {"json": load_response("sources_page_2.json")},
        ],
    )

    output = read_stream(config, "sources")

    assert [message.record.data["type"] for message in output.records] == ["scrape", "zendesk_helpcenter"]
    assert output.records[1].record.data["contains_internal_data"] is True
    assert requests_mock.call_count == 2
    assert parse_qs(urlparse(requests_mock.request_history[1].url).query)["page"] == ["2"]


def test_resource_discovery_exposes_documented_schemas(config):
    catalog = build_source(config).discover(logger=logging.getLogger("source-kapa"), config=config)
    streams = {stream.name: stream for stream in catalog.streams}

    assert len(streams) == 10
    for stream_name in ("integrations", "source_groups", "sources"):
        assert streams[stream_name].source_defined_primary_key == [["id"]]
        assert streams[stream_name].supported_sync_modes == [SyncMode.full_refresh]

    integration_type = streams["integrations"].json_schema["properties"]["integration_type"]
    assert integration_type["type"] == ["null", "string"]
    assert None in integration_type["enum"]

    source_group = streams["source_groups"].json_schema
    assert source_group["properties"]["type"]["enum"] == ["product", "version"]
    assert source_group["properties"]["sub_groups"]["items"]["properties"]["id"]["format"] == "uuid"

    source = streams["sources"].json_schema
    assert "github_files" in source["properties"]["type"]["enum"]
    assert source["properties"]["contains_internal_data"] == {"type": "boolean"}
