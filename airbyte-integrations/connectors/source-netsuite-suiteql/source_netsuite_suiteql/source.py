# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

from collections import Counter
from typing import Any, List, Mapping, Tuple

import requests
from requests_oauthlib import OAuth1

from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream

from .errors import (
    DuplicateTableNameError,
    raise_for_netsuite_status,
)
from .streams import SuiteqlStream
from .validation import SuiteQLTableValidator


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

    def validate_tables(self, config: Mapping[str, Any]) -> None:
        tables = config["tables"]
        names = [table["table_name"] for table in tables]
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            raise DuplicateTableNameError(duplicates)

        for table in tables:
            SuiteQLTableValidator(table).validate()

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        self.validate_tables(config)
        auth = self.auth(config)
        base_url = self.base_url(config)
        page_size = config.get("page_size", 1000)
        tables = config["tables"]

        return [self._get_stream(table=table, base_url=base_url, page_size=page_size, auth=auth) for table in tables]

    def check_connection(self, logger, config: Mapping[str, Any]) -> Tuple[bool, Any]:
        try:
            self.validate_tables(config)
            session = self._get_session(self.auth(config))
            endpoint = self.base_url(config) + SuiteqlStream.api_path

            for table in config["tables"]:
                self._check_table(session, endpoint, table)

            return True, None

        except (KeyError, ValueError, requests.RequestException) as error:
            return False, error

    def _get_session(self, auth: OAuth1) -> requests.Session:
        session = requests.Session()
        session.auth = auth
        return session

    def _check_table(self, session: requests.Session, endpoint: str, table: Mapping[str, Any]) -> None:
        response = session.post(
            endpoint,
            headers={"Prefer": "transient"},
            params={"limit": 1, "offset": 0},
            json={
                "q": SuiteqlStream.build_query(
                    table["table_name"],
                    table["primary_key"],
                    table["cursor_field"],
                )
            },
        )
        raise_for_netsuite_status(response)

    def _get_stream(self, table: Mapping[str, Any], base_url: str, page_size: int, auth: OAuth1) -> SuiteqlStream:
        return SuiteqlStream(
            table_name=table["table_name"],
            base_url=base_url,
            page_size=page_size,
            auth=auth,
            primary_key=table["primary_key"],
            cursor_field=table["cursor_field"],
        )
