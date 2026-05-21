#
# Copyright (c) 2024 Airbyte, Inc., all rights reserved.
#

from dataclasses import dataclass
from threading import Lock
from time import monotonic, sleep
from typing import Any, ClassVar, Mapping, MutableMapping, Optional

from airbyte_cdk.sources.declarative.auth.oauth import DeclarativeSingleUseRefreshTokenOauth2Authenticator
from airbyte_cdk.sources.declarative.requesters.http_requester import HttpRequester
from airbyte_cdk.sources.declarative.types import Config
from airbyte_cdk.sources.declarative.types import StreamSlice, StreamState


@dataclass
class SingleUseOauth2Authenticator(DeclarativeSingleUseRefreshTokenOauth2Authenticator):
    config: Config

    def __post_init__(self):
        self._connector_config = self.config
        self._token_expiry_date_config_path = "credentials/token_expiry_date"
        self.token_refresh_endpoint = "https://accounts.salesloft.com/oauth/token"
        self._access_token_config_path = "credentials/access_token"

    @property
    def auth_header(self) -> str:
        return "Authorization"

    @property
    def token(self) -> str:
        return f"Bearer {self.get_access_token()}"


@dataclass
class ActivityHistoriesHttpRequester(HttpRequester):
    _request_lock: ClassVar[Lock] = Lock()
    _last_request_time: ClassVar[float] = 0.0
    _min_request_interval: ClassVar[float] = 1.5

    def get_request_params(
        self,
        stream_state: Optional[StreamState] = None,
        stream_slice: Optional[StreamSlice] = None,
        next_page_token: Optional[Mapping[str, Any]] = None,
    ) -> MutableMapping[str, Any]:
        params = super().get_request_params(
            stream_state=stream_state,
            stream_slice=stream_slice,
            next_page_token=next_page_token,
        )
        if params.get("type") in ("", None, "None"):
            params.pop("type", None)
        return params

    def send_request(self, *args: Any, **kwargs: Any) -> Any:
        with self._request_lock:
            elapsed = monotonic() - self._last_request_time
            if elapsed < self._min_request_interval:
                sleep(self._min_request_interval - elapsed)
            self._last_request_time = monotonic()

        return super().send_request(*args, **kwargs)
