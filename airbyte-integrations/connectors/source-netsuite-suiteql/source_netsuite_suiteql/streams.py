from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence

import requests
from requests_oauthlib import OAuth1

from airbyte_cdk.sources.streams.http import HttpStream


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
    primary_key = None

    def __init__(
        self,
        name: str,
        query: str,
        parameters: Sequence[Any],
        base_url: str,
        page_size: int,
        auth: OAuth1,
    ) -> None:
        self._name = name
        self.query = query
        self.parameters = list(parameters)
        self._url_base = base_url
        self.page_size = page_size
        self._schema: Optional[Mapping[str, Any]] = None
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

    def path(self, **kwargs) -> str:
        return self.api_path

    def request_headers(self, **kwargs) -> Mapping[str, Any]:
        return {"Prefer": "transient"}

    def request_params(self, next_page_token: Mapping[str, Any] = None, **kwargs) -> MutableMapping[str, Any]:
        return dict(next_page_token or {"limit": self.page_size, "offset": 0})

    def request_body_json(self, **kwargs) -> Mapping[str, Any]:
        body: dict[str, Any] = {"q": self.query}
        if self.parameters:
            body["params"] = self.parameters
        return body

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        payload = response.json()
        if payload.get("hasMore"):
            return {"limit": self.page_size, "offset": payload["offset"] + payload["count"]}
        return None

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping[str, Any]]:
        yield from response.json().get("items", [])

    def get_json_schema(self) -> Mapping[str, Any]:
        if self._schema is None:
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
        return self._schema