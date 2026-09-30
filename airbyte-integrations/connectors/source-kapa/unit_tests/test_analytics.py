# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from conftest import build_source, load_response

from airbyte_cdk.models import SyncMode
from airbyte_cdk.test.catalog_builder import CatalogBuilder
from airbyte_cdk.test.entrypoint_wrapper import read
from airbyte_cdk.test.state_builder import StateBuilder


PROJECT_ID = "d7b46c01-32a3-4f74-80d3-616a3c18fb6b"
BASE_URL = "https://api.kapa.ai/query/v1"
ACTIVITY_URL = f"{BASE_URL}/projects/{PROJECT_ID}/activity/"
TOP_QUESTIONS_PERIODS_URL = f"{BASE_URL}/projects/{PROJECT_ID}/top-questions/periods/"
COVERAGE_GAPS_PERIODS_URL = f"{BASE_URL}/projects/{PROJECT_ID}/coverage-gaps/periods/"


def read_stream(config, stream_name, state=None):
    sync_mode = SyncMode.incremental if stream_name == "activity" else SyncMode.full_refresh
    catalog = CatalogBuilder().with_stream(stream_name, sync_mode).build()
    state = StateBuilder().build() if state is None else state
    return read(build_source(config, state), config, catalog, state)


def test_activity_emits_nested_response_and_date_range(config, requests_mock):
    requests_mock.get(ACTIVITY_URL, json=load_response("activity.json"))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_config = dict(config, start_date=today.strftime("%Y-%m-%dT%H:%M:%SZ"))
    earliest_end = datetime.now(timezone.utc) - timedelta(seconds=1)

    output = read_stream(daily_config, "activity")

    latest_end = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert len(output.records) == 1
    record = output.records[0].record.data
    assert record["aggregate_statistics"] == load_response("activity.json")["aggregate_statistics"]
    assert record["activity_date"] == today.strftime("%Y-%m-%d")
    assert record["window_start"] == today.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert record["is_complete"] is False
    assert requests_mock.call_count == 1

    query = parse_qs(urlparse(requests_mock.last_request.url).query)
    assert query["start_date_time"] == [daily_config["start_date"]]
    end_date_time = datetime.fromisoformat(query["end_date_time"][0].replace("Z", "+00:00"))
    assert earliest_end <= end_date_time <= latest_end


def test_activity_schema_models_observed_nested_statistics(config):
    catalog = build_source(config).discover(logger=logging.getLogger("source-kapa"), config=config)
    activity = next(stream for stream in catalog.streams if stream.name == "activity")

    aggregate = activity.json_schema["properties"]["aggregate_statistics"]
    language = aggregate["properties"]["total_queries_by_language"]["items"]
    integration = activity.json_schema["properties"]["statistics_by_integration"]["items"]

    assert activity.source_defined_primary_key == [["activity_date"]]
    assert activity.default_cursor_field == ["activity_date"]
    assert activity.supported_sync_modes == [SyncMode.full_refresh, SyncMode.incremental]
    assert activity.json_schema["properties"]["activity_date"] == {"type": "string", "format": "date"}
    assert aggregate["properties"]["total_query_count"]["type"] == "integer"
    assert language["properties"] == {
        "iso": {"type": "string"},
        "name": {"type": "string"},
        "count": {"type": "integer"},
    }
    integration_metadata = integration["properties"]["integration"]
    assert integration_metadata["properties"]["id"] == {"type": "string"}
    assert integration_metadata["properties"]["integration_type"]["type"] == ["null", "string"]
    assert integration_metadata["properties"]["name"]["type"] == ["null", "string"]
    assert set(aggregate["required"]) == set(aggregate["properties"])
    assert set(language["required"]) == set(language["properties"])
    assert set(integration["required"]) == {"integration", "statistics"}
    assert integration["properties"]["statistics"] == aggregate


def test_activity_rereads_previous_and_current_day_from_state(config, requests_mock):
    requests_mock.get(ACTIVITY_URL, json=load_response("activity.json"))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    state = StateBuilder().with_stream_state("activity", {"activity_date": today.strftime("%Y-%m-%d")}).build()

    output = read_stream(config, "activity", state)

    assert requests_mock.call_count == 2
    completeness_by_date = {message.record.data["activity_date"]: message.record.data["is_complete"] for message in output.records}
    assert completeness_by_date == {
        yesterday.strftime("%Y-%m-%d"): True,
        today.strftime("%Y-%m-%d"): False,
    }

    queries_by_start = {
        parse_qs(urlparse(request.url).query)["start_date_time"][0]: parse_qs(urlparse(request.url).query)
        for request in requests_mock.request_history
    }
    yesterday_start = yesterday.strftime("%Y-%m-%dT%H:%M:%SZ")
    today_start = today.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert queries_by_start[yesterday_start]["end_date_time"] == [yesterday.strftime("%Y-%m-%dT23:59:59Z")]
    assert today_start in queries_by_start


def test_top_question_periods_use_default_interval_and_paginate(config, requests_mock):
    requests_mock.get(
        TOP_QUESTIONS_PERIODS_URL,
        [
            {"json": load_response("top_questions_periods_page_1.json")},
            {"json": load_response("top_questions_periods_page_2.json")},
        ],
    )

    output = read_stream(config, "top_questions_periods")

    assert [message.record.data["id"] for message in output.records] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    assert output.records[0].record.data == {
        "id": "11111111-1111-4111-8111-111111111111",
        "interval": "monthly",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "total_conversations": 1168,
        "analytics_interval": "monthly",
    }
    assert output.records[1].record.data["total_conversations"] == 0
    assert all(message.record.data["analytics_interval"] == "monthly" for message in output.records)
    assert requests_mock.call_count == 2

    first_query = parse_qs(urlparse(requests_mock.request_history[0].url).query)
    second_query = parse_qs(urlparse(requests_mock.request_history[1].url).query)
    assert first_query["interval"] == ["monthly"]
    assert first_query["page_size"] == ["500"]
    assert "cursor" not in first_query
    assert second_query["cursor"] == ["top-periods-page-2"]


def test_top_question_period_schema_models_observed_fields(config):
    catalog = build_source(config).discover(logger=logging.getLogger("source-kapa"), config=config)
    periods = next(stream for stream in catalog.streams if stream.name == "top_questions_periods")

    assert periods.json_schema["properties"] == {
        "id": {"type": "string", "format": "uuid"},
        "interval": {"type": "string", "enum": ["weekly", "monthly", "quarterly"]},
        "start_date": {"type": "string", "format": "date"},
        "end_date": {"type": "string", "format": "date"},
        "total_conversations": {"type": "integer"},
        "analytics_interval": {"type": "string", "enum": ["weekly", "monthly", "quarterly"]},
    }


def test_top_question_clusters_fan_out_and_paginate(config, requests_mock):
    requests_mock.get(
        TOP_QUESTIONS_PERIODS_URL,
        [
            {"json": load_response("top_questions_periods_page_1.json")},
            {"json": load_response("top_questions_periods_page_2.json")},
        ],
    )
    first_period_url = f"{BASE_URL}/top-questions/periods/11111111-1111-4111-8111-111111111111/"
    requests_mock.get(
        first_period_url,
        [
            {"json": load_response("top_questions_clusters_page_1.json")},
            {"json": load_response("top_questions_clusters_page_2.json")},
        ],
    )
    second_period_url = f"{BASE_URL}/top-questions/periods/22222222-2222-4222-8222-222222222222/"
    requests_mock.get(second_period_url, json=load_response("empty_clusters.json"))

    output = read_stream(config, "top_questions_clusters")

    assert [message.record.data["id"] for message in output.records] == [
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    ]
    assert output.records[0].record.data["num_unique_users"] == 9
    assert output.records[0].record.data["threads"][0] == {
        "id": "77777777-7777-4777-8777-777777777777",
        "created_at": "2026-08-20T10:30:00Z",
        "initial_question": "<redacted question>",
        "initial_answer": "<redacted answer>",
    }
    assert all(message.record.data["period_id"] == "11111111-1111-4111-8111-111111111111" for message in output.records)
    assert all(message.record.data["analytics_interval"] == "monthly" for message in output.records)
    assert requests_mock.call_count == 5

    detail_requests = [request for request in requests_mock.request_history if request.path.startswith("/query/v1/top-questions/periods/")]
    detail_queries = [parse_qs(urlparse(request.url).query) for request in detail_requests]
    assert all(query["page_size"] == ["500"] for query in detail_queries)
    assert any(query.get("cursor") == ["top-clusters-page-2"] for query in detail_queries)


def test_top_question_cluster_schema_models_observed_fields(config):
    catalog = build_source(config).discover(logger=logging.getLogger("source-kapa"), config=config)
    clusters = next(stream for stream in catalog.streams if stream.name == "top_questions_clusters")
    properties = clusters.json_schema["properties"]
    thread = properties["threads"]["items"]

    assert clusters.source_defined_primary_key == [["period_id"], ["id"]]
    assert properties["id"] == {"type": "string", "format": "uuid"}
    assert properties["title"] == {"type": "string"}
    assert properties["summary"] == {"type": ["null", "string"]}
    assert properties["thread_count"] == {"type": "integer"}
    assert properties["num_unique_users"] == {"type": "integer"}
    assert thread["properties"] == {
        "id": {"type": "string", "format": "uuid"},
        "created_at": {"type": "string", "format": "date-time"},
        "initial_question": {"type": "string"},
        "initial_answer": {"type": "string"},
    }


def test_coverage_gap_periods_match_shared_period_contract(config, requests_mock):
    configured_interval = dict(config, analytics_interval="weekly")
    requests_mock.get(COVERAGE_GAPS_PERIODS_URL, json=load_response("coverage_gaps_periods.json"))

    output = read_stream(configured_interval, "coverage_gaps_periods")

    assert [message.record.data for message in output.records] == [
        {
            "id": "55555555-5555-4555-8555-555555555555",
            "interval": "weekly",
            "start_date": "2026-08-24",
            "end_date": "2026-08-30",
            "total_conversations": 116,
            "analytics_interval": "weekly",
        }
    ]
    query = parse_qs(urlparse(requests_mock.last_request.url).query)
    assert query["interval"] == ["weekly"]
    assert query["page_size"] == ["500"]

    catalog = build_source(configured_interval).discover(logger=logging.getLogger("source-kapa"), config=configured_interval)
    top_questions = next(stream for stream in catalog.streams if stream.name == "top_questions_periods")
    coverage_gaps = next(stream for stream in catalog.streams if stream.name == "coverage_gaps_periods")
    assert coverage_gaps.json_schema == top_questions.json_schema


def test_coverage_gap_clusters_preserve_suggestion_and_interval(config, requests_mock):
    configured_interval = dict(config, analytics_interval="weekly")
    requests_mock.get(COVERAGE_GAPS_PERIODS_URL, json=load_response("coverage_gaps_periods.json"))
    detail_url = f"{BASE_URL}/coverage-gaps/periods/55555555-5555-4555-8555-555555555555/"
    requests_mock.get(detail_url, json=load_response("coverage_gaps_clusters.json"))

    output = read_stream(configured_interval, "coverage_gaps_clusters")

    assert len(output.records) == 1
    record = output.records[0].record.data
    assert record["period_id"] == "55555555-5555-4555-8555-555555555555"
    assert record["analytics_interval"] == "weekly"
    assert record["suggestion"] == "Add a compatibility matrix and an FAQ covering the combined workflow."
    assert record["threads"] == [
        {
            "id": "99999999-9999-4999-8999-999999999999",
            "initial_question": "<redacted question>",
            "created_at": "2026-08-31T18:43:01.396887Z",
        }
    ]
    assert requests_mock.call_count == 2

    parent_query = parse_qs(urlparse(requests_mock.request_history[0].url).query)
    assert parent_query["interval"] == ["weekly"]
    assert parent_query["page_size"] == ["500"]


def test_coverage_gap_cluster_schema_models_suggestion_and_key(config):
    catalog = build_source(config).discover(logger=logging.getLogger("source-kapa"), config=config)
    clusters = next(stream for stream in catalog.streams if stream.name == "coverage_gaps_clusters")
    properties = clusters.json_schema["properties"]

    assert clusters.source_defined_primary_key == [["period_id"], ["id"]]
    assert properties["suggestion"] == {"type": ["null", "string"]}
    assert "initial_answer" not in properties["threads"]["items"].get("required", [])
