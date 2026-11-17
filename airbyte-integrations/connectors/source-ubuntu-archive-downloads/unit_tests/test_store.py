# Copyright (c) 2026 Canonical, all rights reserved.

from typing import cast

import pytest
from source_ubuntu_archive_downloads.store import SwiftStore
from swiftclient.client import Connection
from swiftclient.exceptions import ClientException


class FakeConnection:
    """A fake Swift connection. HEAD on a container returns the status given for it, or 204 if none is given."""

    def __init__(self, statuses):
        self.statuses = statuses
        self.heads = []

    def head_container(self, container):
        self.heads.append(container)
        status = self.statuses.get(container, 204)
        if status >= 400:
            raise ClientException("Container HEAD failed", http_status=status)
        return {}


def swift_store(connection: FakeConnection) -> SwiftStore:
    store = SwiftStore.__new__(SwiftStore)
    store._connection = cast(Connection, connection)
    return store


def test_check_reads_the_container_and_its_segments():
    connection = FakeConnection({})
    swift_store(connection).assert_readable("mock-ports-servers")
    assert connection.heads == ["mock-ports-servers", "mock-ports-servers_segments"]


def test_check_passes_when_there_is_no_segments_container():
    swift_store(FakeConnection({"mock-ports-servers_segments": 404})).assert_readable("mock-ports-servers")


@pytest.mark.parametrize("status", [401, 403])
def test_check_fails_without_access_to_the_segments(status):
    with pytest.raises(ClientException):
        swift_store(FakeConnection({"mock-ports-servers_segments": status})).assert_readable("mock-ports-servers")


def test_check_fails_for_a_missing_container():
    connection = FakeConnection({"mock-ports-servers": 404})
    with pytest.raises(ClientException):
        swift_store(connection).assert_readable("mock-ports-servers")
    assert connection.heads == ["mock-ports-servers"]
