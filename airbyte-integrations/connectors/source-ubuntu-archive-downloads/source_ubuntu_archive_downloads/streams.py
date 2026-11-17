# Copyright (c) 2026 Canonical, all rights reserved.

"""
One stream per configured package set.

Each sync lists the log objects in every configured container and reads the ones it hasn't read
yet, oldest first. Each matching line becomes one record, keyed by container, log object and line
number, so reading an object again replaces its rows instead of duplicating them.

State is saved per container after each object is fully read:
- `completed_through`: the date up to which every object has been read.
- `read`: the objects dated after `completed_through` that have been read, with their versions.

`completed_through` stops short of the last `lookback_days` days. Objects in that window are
checked again on every sync, so one that arrives late or changes after it was read is still
picked up.

Raw log lines contain client IPs, so they are never logged. Only counts are: one line per object,
and one line per stream per sync with the packages it matched.
"""

import gzip
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import cached_property, lru_cache
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional

from airbyte_cdk.models.airbyte_protocol import SyncMode
from airbyte_cdk.sources.streams import CheckpointMixin, Stream
from source_ubuntu_archive_downloads.parser import is_access_line, line_prefilter, log_object_date, parse_line


class PackageSetStream(Stream, CheckpointMixin):
    """
    Incremental stream of the downloads that match one package set's patterns.

    Each slice is one log object. Tests can set `today` to fix the lookback window.
    """

    @property
    def primary_key(self) -> List[List[str]]:
        """One record per log line, so reading an object again replaces its rows."""
        return [["container"], ["log_object"], ["line_number"]]

    @property
    def cursor_field(self) -> str:
        """Progress is tracked per log object, in the stream state."""
        return "log_object"

    @property
    def source_defined_cursor(self) -> bool:
        """The cursor is fixed by the connector, not chosen by the user."""
        return True

    def __init__(
        self,
        name: str,
        patterns: List[str],
        containers: List[Mapping[str, str]],
        start_date: str,
        store,
        lookback_days: int = 2,
        today: Optional[date] = None,
    ):
        self._name = name
        self._patterns = patterns
        self._prefilter = line_prefilter(patterns)
        self._containers = containers
        self._start = start_date.replace("-", "")
        self._store = store
        today = today or datetime.now(timezone.utc).date()
        # The latest `completed_through` may reach is the day before the lookback window starts.
        self._completed_through_limit = (today - timedelta(days=lookback_days + 1)).strftime("%Y%m%d")
        self._state: MutableMapping[str, Any] = {}
        self._matched: Counter = Counter()

    @cached_property
    def name(self) -> str:
        """The package set name, used as the stream and table name."""
        return self._name

    @property
    def state(self) -> MutableMapping[str, Any]:
        """Progress per container. The module docstring describes its fields."""
        return self._state

    @state.setter
    def state(self, value: MutableMapping[str, Any]) -> None:
        """Set by the CDK from the saved state when an incremental sync starts."""
        self._state = dict(value or {})

    @lru_cache(maxsize=None)
    def get_json_schema(self) -> Mapping[str, Any]:
        """The record schema, the same for every package set."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "timestamp": {"type": "string", "format": "date-time", "airbyte_type": "timestamp_with_timezone"},
                "package": {"type": "string"},
                "version": {"type": "string"},
                "arch": {"type": "string"},
                "bytes": {"type": ["null", "integer"]},
                "source": {"type": "string"},
                "prodstack": {"type": "string"},
                "container": {"type": "string"},
                "log_object": {"type": "string"},
                "line_number": {"type": "integer"},
            },
        }

    def _container_state(self, container: str, sync_mode: SyncMode) -> Mapping[str, Any]:
        """Return a container's saved state, or an empty one for a full refresh or a container not read yet."""
        state = self._state.get(container) if sync_mode == SyncMode.incremental else None
        return state or {"completed_through": "", "read": {}}

    def stream_slices(
        self,
        *,
        sync_mode: SyncMode,
        cursor_field: Optional[List[str]] = None,
        stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        """
        Yield the log objects still to read, oldest first within each container.

        An object is read if it's dated on or after `start_date` and after `completed_through`, and
        hasn't already been read at its current version.
        """
        self._matched = Counter()
        for container_config in self._containers:
            container = container_config["name"]
            state = self._container_state(container, sync_mode)
            listed = self._store.for_prodstack(container_config["prodstack"]).list_objects(container)
            if listed and not any(log_object_date(name) for name in listed):
                self.logger.warning(f"Container {container} has {len(listed)} objects, but none are named like dated access logs.")
            objects = []
            for name, version in listed.items():
                object_date = log_object_date(name)
                is_new = object_date and object_date >= self._start and object_date > state["completed_through"]
                if is_new and state["read"].get(name) != version:
                    objects.append((object_date, name, version))
            for object_date, name, version in sorted(objects):
                yield {**container_config, "date": object_date, "object": name, "version": version}
        # Slices are read lazily, so this runs once the last slice's records have been read.
        self.logger.info(f"Stream {self.name} matched packages: {dict(sorted(self._matched.items()))}")

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: Optional[List[str]] = None,
        stream_slice: Optional[Mapping[str, Any]] = None,
        stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Iterable[Mapping[str, Any]]:
        """Download and decompress one log object, yield a record per matching line, then mark the object as read."""
        if not stream_slice:
            return
        container, name = stream_slice["name"], stream_slice["object"]
        location = {"source": stream_slice["source"], "prodstack": stream_slice["prodstack"], "container": container, "log_object": name}
        store = self._store.for_prodstack(stream_slice["prodstack"])
        line_number = matched = unparsed = 0
        with store.open_object(container, name) as raw, gzip.GzipFile(fileobj=raw) as lines:
            for line_number, line in enumerate(lines, start=1):
                if self._prefilter and not self._prefilter.search(line):
                    continue
                text = line.decode("utf-8", errors="replace")
                fields = parse_line(text, self._patterns)
                if fields:
                    matched += 1
                    self._matched[fields["package"]] += 1
                    yield {**fields, **location, "line_number": line_number}
                elif not is_access_line(text):
                    unparsed += 1
        if unparsed:
            # The lines themselves hold client IPs, so only the count is logged.
            self.logger.warning(f"{unparsed} candidate lines in {container}/{name} are not in the expected log format.")
        self.logger.info(f"Read {container}/{name}: {line_number} lines, {matched} matched rows, {unparsed} lines failed to parse.")
        # Only reached once the whole object has been read.
        self._mark_read(container, stream_slice["date"], name, stream_slice["version"])

    def _mark_read(self, container: str, object_date: str, name: str, version: str) -> None:
        """Mark an object as read, move `completed_through` forward as far as allowed, and drop the `read` entries it now covers."""
        state = self._state.get(container) or {"completed_through": "", "read": {}}
        # Objects are read in date order, so everything dated before this one is done, but
        # `completed_through` never enters the lookback window, where late objects may still land.
        day_before = (datetime.strptime(object_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        completed_through = max(state["completed_through"], min(day_before, self._completed_through_limit))
        read = {n: v for n, v in state["read"].items() if (log_object_date(n) or "") > completed_through}
        read[name] = version
        self._state[container] = {"completed_through": completed_through, "read": read}
