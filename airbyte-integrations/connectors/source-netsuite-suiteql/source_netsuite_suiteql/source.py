# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import re
from collections import Counter
from typing import Any, List, Mapping, Tuple

import requests
from requests_oauthlib import OAuth1

from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream

from .errors import (
    DuplicateQueryNameError,
    InvalidQueryNameError,
    raise_for_netsuite_status,
)
from .streams import SuiteqlStream
from .validation import SuiteQLQueryValidator


STREAM_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SourceNetsuiteSuiteql(AbstractSource):
    def base_url(self, config: Mapping[str, Any]) -> str:
        account_subdomain = config["realm"].replace("_", "-").lower()
        return f"https://{account_subdomain}.suitetalk.api.netsuite.com"

    def auth(self, config: Mapping[str, Any]) -> OAuth1:
        return OAuth1(
            client_key=config["consumer_key"],
            client_secret=config["consumer_secret"],
            resource_owner_key=config["token_key"],
            resource_owner_secret=config["token_secret"],
            realm=config["realm"].replace("-", "_").upper(),
            signature_method="HMAC-SHA256",
        )

    def validate_queries(self, config: Mapping[str, Any]) -> None:
        queries = config["queries"]
        names = [query["name"] for query in queries]
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            raise DuplicateQueryNameError(duplicates)

        invalid_names = [name for name in names if not STREAM_NAME_PATTERN.fullmatch(name)]
        if invalid_names:
            raise InvalidQueryNameError(invalid_names)

        for query in queries:
            SuiteQLQueryValidator(query).validate()

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        self.validate_queries(config)
        auth = self.auth(config)
        base_url = self.base_url(config)
        page_size = config.get("page_size", 1000)
        queries = config["queries"]

        return [self._get_stream(query=query, base_url=base_url, page_size=page_size, auth=auth) for query in queries]

    def check_connection(self, logger, config: Mapping[str, Any]) -> Tuple[bool, Any]:
        try:
            self.validate_queries(config)
            session = self._get_session(self.auth(config))
            endpoint = self.base_url(config) + SuiteqlStream.api_path

            for query in config["queries"]:
                self._check_query(session, endpoint, query)

            return True, None

        except (KeyError, ValueError, requests.RequestException) as error:
            return False, error

    def _get_session(self, auth: OAuth1) -> requests.Session:
        session = requests.Session()
        session.auth = auth
        return session

    def _check_query(self, session: requests.Session, endpoint: str, query: Mapping[str, Any]) -> None:
        response = session.post(
            endpoint,
            headers={"Prefer": "transient"},
            params={"limit": 1, "offset": 0},
            json=self._query_body(query),
        )
        raise_for_netsuite_status(response)

    def _query_body(self, query: Mapping[str, Any]) -> Mapping[str, Any]:
        body = {"q": query["query"]}

        if query.get("parameters"):
            body["params"] = query["parameters"]

        return body

    def _get_stream(self, query: Mapping[str, Any], base_url: str, page_size: int, auth: OAuth1) -> SuiteqlStream:
        return SuiteqlStream(
            name=query["name"],
            query=query["query"],
            parameters=query.get("parameters", []),
            base_url=base_url,
            page_size=page_size,
            auth=auth,
            primary_key=query.get("primary_key"),
            cursor_field=query.get("cursor_field"),
            cursor_parameter_index=query.get("cursor_parameter_index"),
        )
