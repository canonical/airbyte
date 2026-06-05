# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""
Custom OAuth 2.0 client_credentials authenticator for Skills Base with Thread-Locking.
"""

import threading
import time
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timedelta, timezone
from logging import getLogger
from typing import Any, Mapping, Union

import requests

from airbyte_cdk.config_observation import emit_configuration_as_airbyte_control_message
from airbyte_cdk.models import FailureType
from airbyte_cdk.sources.declarative.auth.declarative_authenticator import DeclarativeAuthenticator
from airbyte_cdk.sources.declarative.interpolation.interpolated_string import InterpolatedString
from airbyte_cdk.sources.declarative.types import Config
from airbyte_cdk.utils import AirbyteTracedException


logger = getLogger("airbyte")

_ACCESS_TOKEN_KEY = "access_token"
_EXPIRY_KEY = "token_expiry_date"
_REFRESH_SAFETY_MARGIN_SECONDS = 60

# Serializes token refreshes so concurrent streams don't slam the endpoint at once.
_AUTH_LOCK = threading.Lock()


@dataclass
class ClientCredentialsConfigUpdaterAuthenticator(DeclarativeAuthenticator):
    """Bearer-token authenticator that caches the token in the connector config across runs."""

    config: Config
    parameters: InitVar[Mapping[str, Any]]
    token_refresh_endpoint: Union[InterpolatedString, str] = ""
    client_id: Union[InterpolatedString, str] = ""
    client_secret: Union[InterpolatedString, str] = ""

    _token_refresh_endpoint: str = field(init=False, repr=False, default="")
    _client_id: str = field(init=False, repr=False, default="")
    _client_secret: str = field(init=False, repr=False, default="")

    def __post_init__(self, parameters: Mapping[str, Any]) -> None:
        self._token_refresh_endpoint = InterpolatedString.create(self.token_refresh_endpoint, parameters=parameters).eval(self.config)
        self._client_id = InterpolatedString.create(self.client_id, parameters=parameters).eval(self.config)
        self._client_secret = InterpolatedString.create(self.client_secret, parameters=parameters).eval(self.config)

    @property
    def auth_header(self) -> str:
        return "Authorization"

    @property
    def token(self) -> str:
        return f"Bearer {self._get_or_refresh_token()}"

    def _get_or_refresh_token(self) -> str:
        with _AUTH_LOCK:
            cached = self.config.get(_ACCESS_TOKEN_KEY)
            expiry_iso = self.config.get(_EXPIRY_KEY)
            if cached and expiry_iso and not self._is_expired(expiry_iso):
                return cached
            return self._refresh_and_persist_token()

    @staticmethod
    def _is_expired(expiry_iso: str) -> bool:
        try:
            expiry = datetime.fromisoformat(expiry_iso)
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expiry - timedelta(seconds=_REFRESH_SAFETY_MARGIN_SECONDS)

    def _refresh_and_persist_token(self) -> str:
        max_auth_retries = 3
        for attempt in range(max_auth_retries):
            try:
                response = requests.post(
                    self._token_refresh_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30,
                )
            except requests.RequestException as e:
                raise AirbyteTracedException(
                    message="Failed to reach the Skills Base OAuth endpoint.",
                    internal_message=f"Network error fetching access token: {e}",
                    failure_type=FailureType.transient_error,
                ) from e

            # Rate limit on the auth endpoint (403/429): back off until reset, then retry.
            if response.status_code in [403, 429] and "rate limit" in response.text.lower():
                reset_timestamp = response.headers.get("X-RateLimit-Reset")
                if reset_timestamp:
                    try:
                        backoff_seconds = max(int(reset_timestamp) - int(time.time()), 0) + 5
                        logger.warning(
                            f"Skills Base Token Endpoint rate limited. "
                            f"Sleeping for {backoff_seconds} seconds until reset window clears (Attempt {attempt + 1}/{max_auth_retries})..."
                        )
                        time.sleep(backoff_seconds)
                        continue
                    except ValueError:
                        pass

                logger.warning("Skills Base Rate limit header missing. Sleeping for 60 seconds as a safety backup...")
                time.sleep(60)
                continue

            # Concurrent active-token cap reached (403/429): unrecoverable without user action.
            if response.status_code in [403, 429] and "allowance exceeded" in response.text.lower():
                raise AirbyteTracedException(
                    message=(
                        "Skills Base reported 'Access token allowance exceeded'. The "
                        "maximum number of concurrent active access tokens is in use. "
                        "Revoke unused tokens in Admin > Settings > API > Manage API "
                        "Keys, or wait for existing tokens to expire, then retry."
                    ),
                    internal_message=response.text,
                    failure_type=FailureType.config_error,
                )

            # Any other failure: bad credentials or subdomain.
            if not response.ok:
                raise AirbyteTracedException(
                    message=(
                        f"Failed to obtain a Skills Base access token. Verify the "
                        f"subdomain, client_id, and client_secret. HTTP Status: {response.status_code}"
                    ),
                    internal_message=f"HTTP {response.status_code}: {response.text}",
                    failure_type=FailureType.config_error,
                )

            payload = response.json()
            access_token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 3600))
            expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Persist to the shared config and emit a control message so the token survives the run.
            self.config[_ACCESS_TOKEN_KEY] = access_token
            self.config[_EXPIRY_KEY] = expiry.isoformat()
            emit_configuration_as_airbyte_control_message(self.config)

            logger.info("Skills Base access token refreshed; expires in %s seconds.", expires_in)
            return access_token

        raise AirbyteTracedException(
            message="Exhausted maximum retries attempting to authenticate due to active Skills Base account rate limits.",
            internal_message="Token refresh endpoint returned persistent rate limit restrictions.",
            failure_type=FailureType.transient_error,
        )
