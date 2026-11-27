import json
import logging
from urllib.parse import parse_qs, urlparse

import pytest
from airbyte_cdk.models import Status, SyncMode
from jsonschema import Draft7Validator

from conftest import CONNECTOR_PATH, RESULTS_URL, build_source, load_response, read_results


LOGGER = logging.getLogger("source-trueability")


def test_read_requests_all_pages_and_preserves_complete_payloads(config, requests_mock):
    # Page 1 has fewer than per_page items while meta.total_pages == 2.
    requests_mock.get(RESULTS_URL, [{"json": load_response(f"results_page_{n}")} for n in (1, 2)])

    output = read_results(config)

    assert not output.errors
    records = [message.record.data for message in output.records]
    expected = (CONNECTOR_PATH / "integration_tests" / "expected_records.jsonl").read_text().splitlines()
    assert records == [json.loads(line) for line in expected]
    result = records[0]["payload"]
    lab, item = result["scenario_tasks"]
    assert lab["commands"][0]["stdout"] == "PASS\n"
    assert lab["commands"][1]["stderr"] == "FAIL\n"
    assert lab["commands"][1]["status"] is False
    assert item["response"] == ["A", "C"]
    assert result["corrected_points_awarded"] == "3.0"
    assert records[1]["payload"]["ability_screen_variant"] is None
    assert records[1]["payload"]["scenario_tasks"][0]["commands"] is None

    assert len(requests_mock.request_history) == 2
    for page, request in enumerate(requests_mock.request_history, start=1):
        assert request.method == "GET"
        assert request.headers["X-API-KEY"] == "test-api-key"
        assert not request.body
        assert parse_qs(urlparse(request.url).query, keep_blank_values=True) == {
            "page": [str(page)],
            "per_page": ["50"],
            "ability_screen_id[]": ["42", "43"],
            "id[]": ["101", "102"],
            "finalized_after": [config["finalized_after"]],
            "finalized_before": [config["finalized_before"]],
        }

    (stream,) = build_source(config).discover(logger=LOGGER, config=config).streams
    assert stream.name == "results"
    assert stream.source_defined_primary_key == [["id"]]
    assert stream.supported_sync_modes == [SyncMode.full_refresh]
    assert stream.json_schema["properties"]["payload"] == {"type": "object", "additionalProperties": True}
    validator = Draft7Validator(stream.json_schema)
    for record in records:
        validator.validate(record)


@pytest.mark.parametrize("body", [{"results": []}, {"results": [], "meta": {"current_page": 1, "total_pages": 0}}])
def test_empty_first_page(config, requests_mock, body):
    requests_mock.get(RESULTS_URL, json=body)

    output = read_results(config)

    assert output.records == []
    assert not output.errors
    assert requests_mock.call_count == 1


@pytest.mark.parametrize("filters", [{}, {"ability_screen_ids": [], "assessment_ids": []}])
def test_no_filters_are_sent_when_none_are_configured(requests_mock, filters):
    requests_mock.get(RESULTS_URL, json={"results": [{"id": 101}], "meta": {"current_page": 1, "total_pages": 1}})

    output = read_results({"api_key": "test-api-key", "page_size": 1, **filters})

    assert not output.errors
    assert [message.record.data for message in output.records] == [{"id": 101, "payload": {"id": 101}}]
    assert requests_mock.call_count == 1
    assert parse_qs(urlparse(requests_mock.last_request.url).query, keep_blank_values=True) == {
        "page": ["1"],
        "per_page": ["1"],
    }


@pytest.mark.parametrize(
    "body,message",
    [
        ({"unexpected": []}, "did not return a results array"),
        ({"results": [{"id": 101}]}, "did not return valid pagination metadata"),
        (
            {"results": [{"user_email": "example@example.test"}], "meta": {"current_page": 1, "total_pages": 1}},
            "has no numeric assessment id",
        ),
    ],
)
def test_invalid_responses_fail_the_sync(config, requests_mock, body, message):
    requests_mock.get(RESULTS_URL, json=body)

    output = read_results(config, expecting_exception=True)

    assert message in str(output.errors)
    assert requests_mock.call_count == 1
    assert output.records == []


@pytest.mark.parametrize(
    "page_two,message",
    [
        ({"results": [{"id": 101}], "meta": {"current_page": 1, "total_pages": 2}}, "returned page 1 when page 2 was requested"),
        ({"results": []}, "did not return valid pagination metadata"),
        ({"results": [], "meta": {"current_page": 2, "total_pages": 2}}, "unexpected empty page"),
    ],
)
def test_invalid_second_page_fails_without_emitting_duplicates(config, requests_mock, page_two, message):
    requests_mock.get(
        RESULTS_URL,
        [{"json": load_response("results_page_1")}, {"json": page_two}, {"status_code": 422}],
    )

    output = read_results(config, expecting_exception=True)

    assert message in str(output.errors)
    assert requests_mock.call_count == 2
    assert [m.record.data["id"] for m in output.records] == [101]


def test_spec_limits_exam_scope_and_page_size(config):
    emitted_spec = build_source(config).spec(logger=LOGGER)
    props = emitted_spec.connectionSpecification["properties"]
    assert emitted_spec.connectionSpecification["required"] == ["api_key"]
    assert props["api_key"]["airbyte_secret"] is True
    assert set(props) == {
        "api_key",
        "ability_screen_ids",
        "assessment_ids",
        "finalized_after",
        "finalized_before",
        "page_size",
    }
    validator = Draft7Validator(emitted_spec.connectionSpecification)
    validator.validate(config)
    assert validator.is_valid({"api_key": "test-api-key"})
    assert validator.is_valid({"api_key": "test-api-key", "ability_screen_ids": [], "assessment_ids": []})
    assert not validator.is_valid({**config, "ability_screen_ids": [0]})
    assert not validator.is_valid({**config, "assessment_ids": [101, 101]})
    assert not validator.is_valid({**config, "page_size": 501})


def test_check_succeeds_when_results_are_accessible(config, requests_mock):
    requests_mock.get(RESULTS_URL, json=load_response("results_page_1"))

    result = build_source(config).check(logger=LOGGER, config=config)

    assert result.status == Status.SUCCEEDED
    assert requests_mock.call_count == 1
