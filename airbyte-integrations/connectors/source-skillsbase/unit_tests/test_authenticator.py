# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""Unit tests for source-skillsbase's custom authenticator (components.py).

These tests exercise the dataclass directly — no Docker, no Skills Base API,
no manifest parsing. Run via `make unit-test`.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest
import requests_mock
from components import (
    _ACCESS_TOKEN_KEY,
    _EXPIRY_KEY,
    ClientCredentialsConfigUpdaterAuthenticator,
)
from requests.exceptions import ConnectionError as RequestsConnectionError

from airbyte_cdk.models import FailureType
from airbyte_cdk.utils import AirbyteTracedException


API_HOST = "https://api.example.com"
TOKEN_URL = f"{API_HOST}/oauth/access_token"


def _make_auth(
    config_overrides: Optional[Dict[str, Any]] = None,
) -> ClientCredentialsConfigUpdaterAuthenticator:
    config: Dict[str, Any] = {
        "api_host": API_HOST,
        "client_id": "cid",
        "client_secret": "csec",
        "start_date": "2024-01-01",
        "access_token": "",
        "token_expiry_date": "",
    }
    if config_overrides:
        config.update(config_overrides)
    return ClientCredentialsConfigUpdaterAuthenticator(
        config=config,
        parameters={},
        token_refresh_endpoint="{{ config['api_host'] }}/oauth/access_token",
        client_id="{{ config['client_id'] }}",
        client_secret="{{ config['client_secret'] }}",
    )


# ---------------------------------------------------------------------------
# _is_expired boundary cases
# ---------------------------------------------------------------------------


class TestIsExpired:
    def test_far_future_is_not_expired(self):
        auth = _make_auth()
        assert auth._is_expired("2099-01-01T00:00:00+00:00") is False

    def test_far_past_is_expired(self):
        auth = _make_auth()
        assert auth._is_expired("2000-01-01T00:00:00+00:00") is True

    def test_within_safety_margin_is_expired(self):
        # 30 s into the future sits inside the 60 s safety margin → treated as expired.
        auth = _make_auth()
        soon = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert auth._is_expired(soon.isoformat()) is True

    def test_just_past_safety_margin_is_not_expired(self):
        auth = _make_auth()
        soon = datetime.now(timezone.utc) + timedelta(seconds=120)
        assert auth._is_expired(soon.isoformat()) is False

    def test_malformed_expiry_treated_as_expired(self):
        auth = _make_auth()
        assert auth._is_expired("not-a-date") is True

    def test_naive_timestamp_assumed_utc(self):
        auth = _make_auth()
        soon_naive = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
        assert auth._is_expired(soon_naive.isoformat()) is False


# ---------------------------------------------------------------------------
# _get_or_refresh_token cache decision
# ---------------------------------------------------------------------------


class TestCacheDecision:
    def test_cache_hit_returns_cached_no_http(self):
        auth = _make_auth(
            {
                "access_token": "TOK",
                "token_expiry_date": "2099-01-01T00:00:00+00:00",
            }
        )
        with requests_mock.Mocker() as m:
            assert auth.token == "Bearer TOK"
            assert m.call_count == 0

    def test_missing_access_token_triggers_refresh(self):
        auth = _make_auth({"token_expiry_date": "2099-01-01T00:00:00+00:00"})
        with requests_mock.Mocker() as m:
            m.post(TOKEN_URL, json={"access_token": "NEW", "expires_in": 3600})
            assert auth.token == "Bearer NEW"
            assert m.call_count == 1

    def test_missing_expiry_triggers_refresh(self):
        auth = _make_auth({"access_token": "OLD"})
        with requests_mock.Mocker() as m:
            m.post(TOKEN_URL, json={"access_token": "NEW", "expires_in": 3600})
            assert auth.token == "Bearer NEW"

    def test_expired_token_triggers_refresh(self):
        auth = _make_auth(
            {
                "access_token": "OLD",
                "token_expiry_date": "2000-01-01T00:00:00+00:00",
            }
        )
        with requests_mock.Mocker() as m:
            m.post(TOKEN_URL, json={"access_token": "NEW", "expires_in": 3600})
            assert auth.token == "Bearer NEW"


# ---------------------------------------------------------------------------
# _refresh_and_persist_token happy path
# ---------------------------------------------------------------------------


class TestRefreshHappyPath:
    def test_refresh_writes_new_token_into_config(self):
        auth = _make_auth()
        with requests_mock.Mocker() as m:
            m.post(TOKEN_URL, json={"access_token": "NEW", "expires_in": 3600})
            assert auth.token == "Bearer NEW"
        assert auth.config[_ACCESS_TOKEN_KEY] == "NEW"
        assert auth.config[_EXPIRY_KEY]

    def test_refresh_expiry_is_now_plus_expires_in(self):
        auth = _make_auth()
        with requests_mock.Mocker() as m:
            m.post(TOKEN_URL, json={"access_token": "NEW", "expires_in": 3600})
            before = datetime.now(timezone.utc)
            assert auth.token == "Bearer NEW"
            after = datetime.now(timezone.utc)
        recorded = datetime.fromisoformat(auth.config[_EXPIRY_KEY])
        assert before + timedelta(seconds=3599) <= recorded <= after + timedelta(seconds=3601)

    def test_refresh_defaults_expires_in_to_3600(self):
        auth = _make_auth()
        with requests_mock.Mocker() as m:
            m.post(TOKEN_URL, json={"access_token": "NEW"})  # no expires_in
            assert auth.token == "Bearer NEW"
        delta = datetime.fromisoformat(auth.config[_EXPIRY_KEY]) - datetime.now(timezone.utc)
        assert timedelta(seconds=3590) <= delta <= timedelta(seconds=3610)


# ---------------------------------------------------------------------------
# _refresh_and_persist_token error branches
# ---------------------------------------------------------------------------


class TestRefreshErrors:
    @pytest.mark.parametrize("status", [403, 429])
    def test_allowance_exceeded_raises_config_error(self, status):
        auth = _make_auth()
        with requests_mock.Mocker() as m:
            m.post(
                TOKEN_URL,
                status_code=status,
                json={"status": "error", "message": "Access token allowance exceeded"},
            )
            with pytest.raises(AirbyteTracedException) as exc:
                _ = auth.token
        assert exc.value.failure_type == FailureType.config_error
        assert "allowance exceeded" in exc.value.message.lower()

    def test_rate_limit_with_reset_header_retries_then_succeeds(self, monkeypatch):
        slept = []
        monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

        reset_at = int(datetime.now(timezone.utc).timestamp()) + 10
        with requests_mock.Mocker() as m:
            m.post(
                TOKEN_URL,
                [
                    {
                        "status_code": 429,
                        "json": {"status": "error", "message": "rate limit exceeded"},
                        "headers": {"X-RateLimit-Reset": str(reset_at)},
                    },
                    {"status_code": 200, "json": {"access_token": "OK", "expires_in": 3600}},
                ],
            )
            auth = _make_auth()
            assert auth.token == "Bearer OK"
            assert m.call_count == 2
        # One sleep, somewhere between 0 s and reset_at + 5 s worth.
        assert len(slept) == 1
        assert 0 <= slept[0] <= 20

    def test_rate_limit_without_header_sleeps_60s(self, monkeypatch):
        slept = []
        monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

        with requests_mock.Mocker() as m:
            m.post(
                TOKEN_URL,
                [
                    {
                        "status_code": 429,
                        "json": {"status": "error", "message": "rate limit exceeded"},
                    },
                    {"status_code": 200, "json": {"access_token": "OK", "expires_in": 3600}},
                ],
            )
            auth = _make_auth()
            assert auth.token == "Bearer OK"
        assert 60 in slept

    def test_persistent_rate_limit_eventually_raises_transient(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda s: None)
        with requests_mock.Mocker() as m:
            m.post(
                TOKEN_URL,
                status_code=429,
                json={"status": "error", "message": "rate limit exceeded"},
            )
            auth = _make_auth()
            with pytest.raises(AirbyteTracedException) as exc:
                _ = auth.token
        assert exc.value.failure_type == FailureType.transient_error

    def test_other_4xx_raises_config_error(self):
        auth = _make_auth()
        with requests_mock.Mocker() as m:
            m.post(
                TOKEN_URL,
                status_code=401,
                json={"status": "error", "message": "bad credentials"},
            )
            with pytest.raises(AirbyteTracedException) as exc:
                _ = auth.token
        assert exc.value.failure_type == FailureType.config_error

    def test_network_failure_raises_transient(self):
        auth = _make_auth()
        with requests_mock.Mocker() as m:
            m.post(TOKEN_URL, exc=RequestsConnectionError("connection refused"))
            with pytest.raises(AirbyteTracedException) as exc:
                _ = auth.token
        assert exc.value.failure_type == FailureType.transient_error
