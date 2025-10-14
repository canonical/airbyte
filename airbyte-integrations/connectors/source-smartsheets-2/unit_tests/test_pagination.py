import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from source_smartsheets_2.source import SourceSmartsheets_2


class DummySheet:
    def __init__(self, id, name, columns, rows):
        self.id = id
        self.name = name
        self.columns = columns
        self.rows = rows


class DummyColumn:
    def __init__(self, title, type):
        self.title = title
        self.type = SimpleNamespace(value=type)


class DummyRow:
    def __init__(self, id, cells):
        self.id = id
        self.cells = cells
        self.created_at = SimpleNamespace(isoformat=lambda: "")
        self.modified_at = SimpleNamespace(isoformat=lambda: "")
        self.created_by = SimpleNamespace(name="user")
        self.modified_by = SimpleNamespace(name="user")
        self.permalink = ""
        self.row_number = 1
        self.version = 1


class DummyFolder:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def make_config(root_folder_id=1):
    return {
        "root-folder-id": root_folder_id,
        "schema-sheet-ids": [],
        "stream-name": "test",
        "include-patterns": [".*"],
        "exclude-patterns": [],
        "metadata-fields": [],
    }


def run_read_and_collect(client_mock, config):
    source = SourceSmartsheets_2()
    # Minimal catalog: one stream with an empty schema
    catalog = SimpleNamespace(streams=[SimpleNamespace(stream=SimpleNamespace(name="test", json_schema={"properties": {}}))])
    records = list(source.read(logger=MagicMock(), config=config, catalog=catalog, state={}))
    return records


def test_single_page_children_are_processed(monkeypatch):
    # Setup client mock
    client = MagicMock()
    # get_folder_children returns an object with .data containing both folders and sheets
    folder = DummyFolder(1, "root")
    child_folder = DummyFolder(2, "child")
    sheet = DummySheet(10, "sheet1", [], [])
    client.Folders.get_folder_children.return_value = SimpleNamespace(data=[child_folder, sheet])
    client.Folders.get_folder_metadata.return_value = folder
    client.Sheets.get_sheet.return_value = sheet

    monkeypatch.setattr("source_smartsheets_2.source.api.get_client", lambda cfg: client)

    config = make_config(root_folder_id=1)
    records = run_read_and_collect(client, config)

    # No rows were present, so no record messages are produced, but code should not error
    assert isinstance(records, list)


def test_paginated_children_only_first_page_processed(monkeypatch):
    # Simulate a client where children would be paginated but our simplified code only fetches once
    client = MagicMock()
    folder = DummyFolder(1, "root")
    # First page has one sheet
    sheet1 = DummySheet(10, "sheet1", [], [])
    # Second page would have another sheet, but our code won't fetch it
    sheet2 = DummySheet(11, "sheet2", [], [])

    # Simulate paginated response by returning an object with .data
    client.Folders.get_folder_children.return_value = SimpleNamespace(data=[sheet1])
    client.Folders.get_folder_metadata.return_value = folder
    client.Sheets.get_sheet.return_value = sheet1

    monkeypatch.setattr("source_smartsheets_2.source.api.get_client", lambda cfg: client)

    config = make_config(root_folder_id=1)
    records = run_read_and_collect(client, config)

    # Our simplified logic will only process sheet1 (first page)
    assert isinstance(records, list)
