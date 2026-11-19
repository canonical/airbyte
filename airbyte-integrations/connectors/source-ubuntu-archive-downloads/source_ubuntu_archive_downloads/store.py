# Copyright (c) 2026 Canonical, all rights reserved.

"""
Where the log objects are read from.

`SwiftStore` reads the log containers through the Swift API. Swift keeps the parts of large
objects in a separate `<container>_segments` container and joins them on the server, so the
service account needs read access to those containers too.

Each Prodstack is a separate cloud with its own Keystone and radosgw endpoints. `SwiftStores`
therefore holds one `SwiftStore` per Prodstack, and each container is read through the store
for its Prodstack.

`LocalStore` reads the same layout from a local directory (`<root>/<container>/<object name>`),
so the connector can be run end to end against mock archives. It serves every Prodstack.
"""

import io
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, Iterator, List, Mapping

from swiftclient.client import Connection
from swiftclient.exceptions import ClientException


CHUNK_SIZE = 1024 * 1024


class _ChunkReader(io.RawIOBase):
    """A read-only file object that streams a download from an iterator of byte chunks."""

    def __init__(self, chunks: Iterable[bytes]):
        self._body = chunks
        self._chunks: Iterator[bytes] = iter(chunks)
        self._buffer = b""

    def close(self) -> None:
        """
        Close the download.

        swiftclient only closes a chunked response once it's fully read, and the connection can't
        make another request while one is still open.
        """
        if not self.closed:
            close_body = getattr(self._body, "close", None)
            if close_body:
                close_body()
        super().close()

    def readable(self) -> bool:
        """Always true: this file object only supports reading."""
        return True

    def readinto(self, target) -> int:
        """Copy bytes into `target`, fetching the next chunk when the current one is used up. Returns 0 at the end."""
        while not self._buffer:
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self._buffer = chunk
        size = min(len(target), len(self._buffer))
        target[:size] = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return size


class SwiftStore:
    """Reads the log containers of one Prodstack, through its Keystone v3 and Swift endpoints."""

    def __init__(self, config: Mapping[str, str]):
        self._connection = Connection(
            authurl=config["auth_url"],
            user=config["username"],
            key=config["password"],
            auth_version="3",
            os_options={
                "project_name": config["project_name"],
                "user_domain_name": config.get("user_domain_name", "Default"),
                "project_domain_name": config.get("project_domain_name", "Default"),
            },
            retries=5,
        )

    def assert_readable(self, container: str) -> None:
        """
        Raise if the container, or its `<container>_segments` container, can't be read.

        A missing `_segments` container is fine: it only exists when logs are stored as large objects.
        """
        self._connection.head_container(container)
        try:
            self._connection.head_container(f"{container}_segments")
        except ClientException as e:
            if e.http_status != 404:
                raise

    def list_objects(self, container: str) -> Dict[str, str]:
        """Map each object name to its last-modified time, which changes when the object is rewritten."""
        _, objects = self._connection.get_container(container, full_listing=True)
        return {obj["name"]: obj["last_modified"] for obj in objects}

    def open_object(self, container: str, name: str) -> BinaryIO:
        """Open an object for streaming in 1 MiB chunks, without holding it in memory."""
        _, chunks = self._connection.get_object(container, name, resp_chunk_size=CHUNK_SIZE)
        return io.BufferedReader(_ChunkReader(chunks), buffer_size=CHUNK_SIZE)


class SwiftStores:
    """Holds one `SwiftStore` per Prodstack endpoint."""

    def __init__(self, endpoints: List[Mapping[str, str]]):
        prodstacks = [endpoint["prodstack"] for endpoint in endpoints]
        repeated = sorted({p for p in prodstacks if prodstacks.count(p) > 1})
        if repeated:
            raise ValueError(f"Each Prodstack needs exactly one endpoint, but these have more than one: {', '.join(repeated)}")
        self._stores = {endpoint["prodstack"]: SwiftStore(endpoint) for endpoint in endpoints}

    def for_prodstack(self, prodstack: str) -> SwiftStore:
        """Return the store for a Prodstack. Raises if that Prodstack has no endpoint configured."""
        if prodstack not in self._stores:
            raise ValueError(f"No Swift endpoint is configured for Prodstack {prodstack!r}")
        return self._stores[prodstack]


class LocalStore:
    """Same interface as `SwiftStore`, but reads from a local directory. Used for testing, and serves every Prodstack."""

    def __init__(self, root: str):
        self._root = Path(root)

    def for_prodstack(self, prodstack: str) -> "LocalStore":
        """Return this store: one local directory stands in for every Prodstack."""
        return self

    def assert_readable(self, container: str) -> None:
        """Raise if the container has no directory under the root."""
        if not (self._root / container).is_dir():
            raise FileNotFoundError(f"No directory for container {container} under {self._root}")

    def list_objects(self, container: str) -> Dict[str, str]:
        """Map each file in the container to its modification time, which stands in for Swift's last-modified time."""
        base = self._root / container
        return {str(path.relative_to(base)): str(path.stat().st_mtime_ns) for path in sorted(base.rglob("*")) if path.is_file()}

    def open_object(self, container: str, name: str) -> BinaryIO:
        """Open the object's file for reading."""
        return open(self._root / container / name, "rb")


def make_store(storage: Mapping[str, Any]):
    """Build the store for the `storage` config: `SwiftStores` for Swift, or `LocalStore` for a local directory."""
    if storage["type"] == "swift":
        return SwiftStores(storage["endpoints"])
    if storage["type"] == "local":
        return LocalStore(storage["path"])
    raise ValueError(f"Unknown storage type: {storage['type']}")
