from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import requests
from requests_oauthlib import OAuth1

from airbyte_cdk.sources.streams.http import HttpStream

from .errors import MissingCursorFieldError


JSON_TYPES = {
    type(None): "null",
    bool: "boolean",
    int: "integer",
    float: "number",
    dict: "object",
    list: "array",
    str: "string",
}


def json_type(value: Any) -> list[str]:
    value_type = JSON_TYPES.get(type(value), "string")
    return ["null"] if value_type == "null" else ["null", value_type]


class SuiteqlStream(HttpStream):
    api_path = "/services/rest/query/v1/suiteql"

    def __init__(
        self,
        name: str,
        query: str,
        parameters: Sequence[Any],
        base_url: str,
        page_size: int,
        auth: OAuth1,
        primary_key: Sequence[str] | None = None,
        cursor_field: str | None = None,
        cursor_parameter_index: int | None = None,
    ) -> None:
        self._name = name
        self.query = query
        self.parameters = list(parameters)
        self._url_base = base_url
        self.page_size = page_size
        self._primary_key = [[field] for field in primary_key] if primary_key else None
        self._cursor_field = cursor_field or []
        self.cursor_parameter_index = cursor_parameter_index
        self._schema: Mapping[str, Any] | None = None
        super().__init__(authenticator=auth)

    @property
    def name(self) -> str:
        return self._name

    @property
    def url_base(self) -> str:
        return self._url_base

    @property
    def http_method(self) -> str:
        return "POST"

    @property
    def cursor_field(self) -> str | list[str]:
        return self._cursor_field

    @property
    def primary_key(self) -> list[list[str]] | None:
        return self._primary_key

    @property
    def is_resumable(self) -> bool:
        return self.supports_incremental

    def path(self, **kwargs) -> str:
        return self.api_path

    def request_headers(self, **kwargs) -> Mapping[str, Any]:
        return {"Prefer": "transient"}

    def request_params(
        self,
        stream_state: Mapping[str, Any] | None, # needed by CDK
        stream_slice: Mapping[str, Any] | None = None, # needed by CDK
        next_page_token: Mapping[str, Any] | None = None,
    ) -> MutableMapping[str, Any]:
        return dict(next_page_token or {"limit": self.page_size, "offset": 0})

    def request_body_json(self, stream_state: Mapping[str, Any] | None = None, **kwargs) -> Mapping[str, Any]:
        body: dict[str, Any] = {"q": self.query}
        parameters = self.parameters.copy()

        if self.cursor_parameter_index is not None and stream_state:
            cursor = stream_state.get(self.cursor_field)

            if cursor is not None:
                parameters[self.cursor_parameter_index] = cursor

        if parameters:
            body["params"] = parameters

        return body

    def get_updated_state(
        self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        cursor_field = self.cursor_field
        if not cursor_field:
            return current_stream_state

        latest_cursor = latest_record.get(cursor_field)
        if latest_cursor is None:
            raise MissingCursorFieldError(cursor_field)
        
        current_cursor = current_stream_state.get(cursor_field)
        return {cursor_field: max(cursor for cursor in (current_cursor, latest_cursor) if cursor is not None)}

    def next_page_token(self, response: requests.Response) -> Mapping[str, Any] | None:
        payload = response.json()
        if payload.get("hasMore"):
            return {"limit": self.page_size, "offset": payload["offset"] + payload["count"]}
        return None

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping[str, Any]]:
        yield from response.json().get("items", [])

    def get_json_schema(self) -> Mapping[str, Any]:
        if self._schema is None:
            self._reset_schema()
        return self._schema

    def _reset_schema(self) -> None:
        response = self._session.post(
            self.url_base + self.api_path,
            headers=self.request_headers(),
            params={"limit": 1, "offset": 0},
            json=self.request_body_json(),
        )
        response.raise_for_status()
        records = response.json().get("items", [])
        properties = {key: {"type": json_type(value)} for key, value in records[0].items()} if records else {}
        self._schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "properties": properties}