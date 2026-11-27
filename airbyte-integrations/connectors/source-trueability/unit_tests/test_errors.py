import logging

import pytest
from airbyte_cdk.models import Status

from conftest import RESULTS_URL, build_source, load_response, read_results


def test_authentication_error_fails_check_without_retries(config, requests_mock):
    requests_mock.get(RESULTS_URL, status_code=401, json={"message": "Permission denied"})

    result = build_source(config).check(logger=logging.getLogger("source-trueability"), config=config)

    assert result.status == Status.FAILED
    assert "TrueAbility API key" in result.message
    assert requests_mock.call_count == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_error_retries_the_same_page(config, requests_mock, mocker, status):
    mocker.patch("time.sleep")
    requests_mock.get(
        RESULTS_URL,
        [
            {"json": load_response("results_page_1")},
            {"status_code": status, "headers": {"Retry-After": "1"}},
            {"json": load_response("results_page_2")},
        ],
    )

    output = read_results(config)

    assert not output.errors
    assert [message.record.data["id"] for message in output.records] == [101, 102]
    assert requests_mock.call_count == 3
    assert requests_mock.request_history[1].url == requests_mock.request_history[2].url


def test_permanent_error_on_second_page_fails_instead_of_truncating(config, requests_mock):
    requests_mock.get(RESULTS_URL, [{"json": load_response("results_page_1")}, {"status_code": 404}])

    output = read_results(config, expecting_exception=True)

    assert "TrueAbility API key" in str(output.errors)
    assert requests_mock.call_count == 2


def test_transient_retries_are_bounded(config, requests_mock, mocker):
    mocker.patch("time.sleep")
    requests_mock.get(RESULTS_URL, status_code=500, json={"message": "Internal Server Error"})

    output = read_results(config, expecting_exception=True)

    assert output.records == []
    assert output.errors
    assert requests_mock.call_count == 4
