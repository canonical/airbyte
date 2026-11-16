# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""Mocked-HTTP tests for the Skill Query (POST /2.0/skillquery) streams in manifest.yaml."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import requests_mock
import yaml

from airbyte_cdk.models import ConfiguredAirbyteCatalog, ConfiguredAirbyteCatalogSerializer, SyncMode, Type
from airbyte_cdk.sources.declarative.concurrent_declarative_source import ConcurrentDeclarativeSource


API_HOST = "https://api.skills-base.test"
SKILL_QUERY_URL = f"{API_HOST}/2.0/skillquery"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "manifest.yaml"
PAGE_SIZE = 500


@pytest.fixture
def config() -> Dict[str, Any]:
    # A cached, unexpired token keeps the authenticator from calling /oauth/access_token.
    return {
        "api_host": API_HOST,
        "client_id": "client-id",
        "client_secret": "client-secret",
        "start_date": "2024-01-01",
        "access_token": "cached-token",
        "token_expiry_date": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }


def _source(config: Dict[str, Any], catalog: ConfiguredAirbyteCatalog) -> ConcurrentDeclarativeSource:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    return ConcurrentDeclarativeSource(catalog=catalog, config=config, state=None, source_config=manifest)


def _catalog(stream_name: str) -> ConfiguredAirbyteCatalog:
    return ConfiguredAirbyteCatalogSerializer.load(
        {
            "streams": [
                {
                    "stream": {"name": stream_name, "json_schema": {}, "supported_sync_modes": ["full_refresh"]},
                    "sync_mode": SyncMode.full_refresh.value,
                    "destination_sync_mode": "overwrite",
                }
            ]
        }
    )


def _row(*values: Optional[Any]) -> Dict[str, Any]:
    return {"values": [{"data": value} for value in values]}


def _page(rows: List[Dict[str, Any]], total: int, offset: int) -> Dict[str, Any]:
    return {
        "status": "success",
        "data": {"columns": [], "rows": rows, "totalRows": total, "offset": offset, "limit": PAGE_SIZE},
    }


def _read(config: Dict[str, Any], stream_name: str) -> List[Dict[str, Any]]:
    catalog = _catalog(stream_name)
    source = _source(config, catalog)
    messages = source.read(logger=source.logger, config=config, catalog=catalog, state=None)
    return [message.record.data for message in messages if message.type == Type.RECORD]


def test_role_competencies_maps_positional_values_and_casts_ids(config: Dict[str, Any]) -> None:
    with requests_mock.Mocker() as mocker:
        mocker.post(SKILL_QUERY_URL, json=_page([_row("47", "21", 50), _row("47", "25", 0)], total=2, offset=0))

        records = _read(config, "role_competencies")

    assert records == [
        {"role_id": 47, "skill_id": 21, "competency": 50},
        {"role_id": 47, "skill_id": 25, "competency": 0},
    ]
    body = json.loads(mocker.request_history[0].body)
    assert body["query"].startswith("find role skills show role.id, skill.id, competency")


def test_role_competencies_drops_rows_without_primary_key(config: Dict[str, Any]) -> None:
    with requests_mock.Mocker() as mocker:
        mocker.post(
            SKILL_QUERY_URL,
            json=_page([_row(None, "21", 50), _row("47", None, 40), _row("47", "22", 40)], total=3, offset=0),
        )

        records = _read(config, "role_competencies")

    assert records == [{"role_id": 47, "skill_id": 22, "competency": 40}]


def test_person_competencies_maps_all_competency_columns(config: Dict[str, Any]) -> None:
    with requests_mock.Mocker() as mocker:
        mocker.post(
            SKILL_QUERY_URL,
            json=_page([_row("1", "21", 80, 90, 70), _row("1", "22", None, None, None)], total=2, offset=0),
        )

        records = _read(config, "person_competencies")

    assert records[0] == {"person_id": 1, "skill_id": 21, "competency": 80, "competency_self": 90, "competency_supervisor": 70}
    assert records[1]["person_id"] == 1 and records[1]["skill_id"] == 22
    assert records[1].get("competency") is None


@pytest.mark.parametrize("stream_name", ["role_competencies", "person_competencies", "training_completions"])
def test_skill_query_streams_paginate_by_row_offset(config: Dict[str, Any], stream_name: str) -> None:
    total = PAGE_SIZE + 2
    rows = [_row(str(i), str(i), 10, 10, 10) for i in range(1, total + 1)]

    def respond(request, context):
        offset = int(request.qs["start_index"][0])
        limit = int(request.qs["limit"][0])
        return _page(rows[offset : offset + limit], total=total, offset=offset)

    with requests_mock.Mocker() as mocker:
        mocker.post(SKILL_QUERY_URL, json=respond)

        records = _read(config, stream_name)

    assert len(records) == total
    assert [(r.qs["start_index"][0], r.qs["limit"][0]) for r in mocker.request_history] == [
        ("0", str(PAGE_SIZE)),
        (str(PAGE_SIZE), str(PAGE_SIZE)),
    ]
