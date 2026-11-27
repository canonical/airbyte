# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import json
from pathlib import Path

import pytest

from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources.declarative.yaml_declarative_source import YamlDeclarativeSource
from airbyte_cdk.test.catalog_builder import CatalogBuilder
from airbyte_cdk.test.entrypoint_wrapper import read
from airbyte_cdk.test.state_builder import StateBuilder


CONNECTOR_PATH = Path(__file__).resolve().parents[1]
RESULTS_URL = "https://app.trueability.com/api/v1/results"


def load_response(name):
    return json.loads((CONNECTOR_PATH / "unit_tests" / "responses" / f"{name}.json").read_text())


@pytest.fixture
def config():
    return json.loads((CONNECTOR_PATH / "integration_tests" / "sample_config.json").read_text())


def build_source(config, catalog=None):
    return YamlDeclarativeSource(
        path_to_yaml=str(CONNECTOR_PATH / "manifest.yaml"),
        catalog=catalog if catalog is not None else CatalogBuilder().build(),
        config=config,
        state=StateBuilder().build(),
    )


def read_results(config, *, expecting_exception=False):
    catalog = CatalogBuilder().with_stream("results", SyncMode.full_refresh).build()
    return read(build_source(config, catalog), config, catalog, StateBuilder().build(), expecting_exception)
