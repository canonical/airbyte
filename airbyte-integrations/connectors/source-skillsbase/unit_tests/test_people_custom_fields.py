# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""Tests for the `people` stream mapping of `custom_field_{id}` values to `hire_date` / `competency`."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests_mock
import yaml

from airbyte_cdk.models import ConfiguredAirbyteCatalog, ConfiguredAirbyteCatalogSerializer, Type
from airbyte_cdk.sources.declarative.concurrent_declarative_source import ConcurrentDeclarativeSource


API_HOST = "https://api.skills-base.test"
MANIFEST = yaml.safe_load((Path(__file__).resolve().parent.parent / "manifest.yaml").read_text())

PEOPLE = [
    {"id": 1, "custom_field_1": "2020-03-01", "custom_field_3": "4"},
    {"id": 2, "custom_field_1": "", "custom_field_3": None},
    {"id": 3},
]


def _config(**custom_field_ids: int) -> Dict[str, Any]:
    # A cached, unexpired token keeps the authenticator from calling /oauth/access_token.
    return {
        "api_host": API_HOST,
        "client_id": "client-id",
        "client_secret": "client-secret",
        "access_token": "cached-token",
        "token_expiry_date": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        **custom_field_ids,
    }


def _catalog() -> ConfiguredAirbyteCatalog:
    return ConfiguredAirbyteCatalogSerializer.load(
        {
            "streams": [
                {
                    "stream": {"name": "people", "json_schema": {}, "supported_sync_modes": ["full_refresh"]},
                    "sync_mode": "full_refresh",
                    "destination_sync_mode": "overwrite",
                }
            ]
        }
    )


def _read_people(config: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    catalog = _catalog()
    source = ConcurrentDeclarativeSource(catalog=catalog, config=config, state=None, source_config=MANIFEST)
    with requests_mock.Mocker() as mocker:
        mocker.get(f"{API_HOST}/1.0/people", [{"json": {"data": PEOPLE}}, {"json": {"data": []}}])
        records: List[Dict[str, Any]] = [
            message.record.data for message in source.read(source.logger, config, catalog, None) if message.type == Type.RECORD
        ]
    assert sorted(record["id"] for record in records) == [person["id"] for person in PEOPLE]
    return {record["id"]: record for record in records}


def test_configured_ids_map_custom_fields_as_strings() -> None:
    people = _read_people(_config(hire_date_custom_field_id=1, competency_custom_field_id=3))

    assert people[1]["hire_date"] == "2020-03-01"
    # Value-list answers stay strings; the CDK would otherwise coerce "4" to an int.
    assert people[1]["competency"] == "4"
    assert people[1]["custom_field_3"] == "4"


def test_configured_ids_with_missing_values_yield_null_or_empty() -> None:
    people = _read_people(_config(hire_date_custom_field_id=1, competency_custom_field_id=3))

    assert people[2]["hire_date"] == ""
    assert people[2]["competency"] is None
    assert people[3]["hire_date"] is None
    assert people[3]["competency"] is None


@pytest.mark.parametrize(
    "custom_field_ids",
    [pytest.param({}, id="unset"), pytest.param({"hire_date_custom_field_id": 99, "competency_custom_field_id": 98}, id="unknown-ids")],
)
def test_unset_or_unknown_ids_leave_fields_null(custom_field_ids: Dict[str, int]) -> None:
    people = _read_people(_config(**custom_field_ids))

    assert all(person["hire_date"] is None and person["competency"] is None for person in people.values())
