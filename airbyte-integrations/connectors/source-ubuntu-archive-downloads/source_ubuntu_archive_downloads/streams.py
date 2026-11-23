# Copyright (c) 2026 Canonical, all rights reserved.

"""
One stream per configured package set.

Each sync lists the log objects in every configured container and reads the ones it hasn't read
yet, oldest first. Each matching line becomes one record, keyed by Prodstack, container, log object
and line number, so reading an object again overwrites rows with the same line numbers instead of
duplicating them. Rows for lines that no longer match aren't removed, so a regenerated object needs a
Clear data in Airbyte.

State is saved per container after each object is fully read, under `<prodstack>/<container>`:
- `completed_through`: the date up to which every object has been read.
- `read`: the objects dated after `completed_through` that have been read, with their last-modified times.

An object's records are only sent once the whole object has been read. An object that fails to
read, for example a truncated gzip, sends no records, is not marked as read, and holds its
container's `completed_through` below its date. The stream reads everything else, then fails, naming
the objects, so the next sync retries them and the failure shows in Airbyte.

`completed_through` stops short of the last `lookback_days` days. Objects in that window are
checked again on every sync, so one that arrives late or changes after it was read is still
picked up.

Raw log lines contain client IPs, so they are never logged. Only counts are: one line per object,
and one line per stream per sync with the packages it matched.
"""

import gzip
import json
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import cached_property, lru_cache
from typing import IO, Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

from airbyte_cdk.models.airbyte_protocol import FailureType, SyncMode
from airbyte_cdk.sources.streams import CheckpointMixin, Stream
from airbyte_cdk.utils.traced_exception import AirbyteTracedException
from source_ubuntu_archive_downloads.parser import is_access_line, line_prefilter, log_object_date, parse_line


RECORD_SCHEMA: Mapping[str, Any] = {
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


class PackageSetStream(Stream, CheckpointMixin):
    """
    Incremental stream of the downloads that match one package set's patterns.

    Each slice is one log object. Tests can set `today` to fix the lookback window.
    """

    @property
    def primary_key(self) -> List[List[str]]:
        """One record per log line, so reading an object again overwrites rows with the same line numbers."""
        return [["prodstack"], ["container"], ["log_object"], ["line_number"]]

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
        # Objects that failed to read in this sync, and the latest `completed_through` each container may reach.
        self._failed: List[str] = []
        self._held: Dict[str, str] = {}

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
        return RECORD_SCHEMA

    @staticmethod
    def _state_key(prodstack: str, container: str) -> str:
        """The state key of a container. Swift container names can't contain `/`, so it's unambiguous."""
        return f"{prodstack}/{container}"

    def _container_state(self, key: str) -> Mapping[str, Any]:
        """Return a container's saved state, or an empty one for a container not read yet."""
        return self._state.get(key) or {"completed_through": "", "read": {}}

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
        hasn't already been read at its current last-modified time.
        """
        self._matched = Counter()
        self._failed, self._held = [], {}
        if sync_mode == SyncMode.full_refresh:
            # A full refresh reads everything and starts its state from scratch.
            self._state = {}
        for container_config in self._containers:
            container, prodstack = container_config["name"], container_config["prodstack"]
            state = self._container_state(self._state_key(prodstack, container))
            listed = self._store.for_prodstack(prodstack).list_objects(container)
            if listed and not any(log_object_date(name) for name in listed):
                self.logger.warning(f"Container {container} has {len(listed)} objects, but none are named like dated access logs.")
            objects = []
            for name, last_modified in listed.items():
                object_date = log_object_date(name)
                is_new = object_date and object_date >= self._start and object_date > state["completed_through"]
                if is_new and state["read"].get(name) != last_modified:
                    objects.append((object_date, name, last_modified))
            for object_date, name, last_modified in sorted(objects):
                yield {**container_config, "date": object_date, "object": name, "last_modified": last_modified}
        # Slices are read lazily, so this runs once the last slice's records have been read.
        self.logger.info(f"Stream {self.name} matched packages: {dict(sorted(self._matched.items()))}")
        if self._failed:
            raise AirbyteTracedException(
                message=f"Stream {self.name} could not read {len(self._failed)} log objects. They will be retried on the next sync.",
                internal_message=f"Failed objects: {', '.join(self._failed)}",
                failure_type=FailureType.system_error,
            )

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: Optional[List[str]] = None,
        stream_slice: Optional[Mapping[str, Any]] = None,
        stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Iterable[Mapping[str, Any]]:
        """
        Download and decompress one log object, then yield a record per matching line and mark the object as read.

        Matches are held in a temporary file until the whole object has been read, so an object that
        fails partway yields nothing, and memory stays flat however many lines match.
        """
        if not stream_slice:
            return
        container, name = stream_slice["name"], stream_slice["object"]
        location = {"source": stream_slice["source"], "prodstack": stream_slice["prodstack"], "container": container, "log_object": name}
        store = self._store.for_prodstack(stream_slice["prodstack"])
        packages: Counter = Counter()
        counts: Counter = Counter()
        with tempfile.TemporaryFile() as matches:
            try:
                with store.open_object(container, name) as raw, gzip.GzipFile(fileobj=raw) as lines:
                    self._write_matches(lines, matches, packages, counts)
            except Exception as e:
                self._fail(stream_slice, counts["lines"], e)
                return

            matches.seek(0)
            for match in matches:
                yield {**json.loads(match), **location}

        self._matched.update(packages)
        if counts["unparsed"]:
            # The lines themselves hold client IPs, so only the count is logged.
            self.logger.warning(f"{counts['unparsed']} candidate lines in {container}/{name} are not in the expected log format.")
        matched = sum(packages.values())
        self.logger.info(
            f"Read {container}/{name}: {counts['lines']} lines, {matched} matched rows, {counts['unparsed']} lines failed to parse."
        )
        self._mark_read(self._state_key(stream_slice["prodstack"], container), stream_slice["date"], name, stream_slice["last_modified"])

    def _write_matches(self, lines: Iterable[bytes], matches: IO[bytes], packages: Counter, counts: Counter) -> None:
        """
        Write the fields of each matching line to `matches`, one JSON line each, and count the matches
        per package. `counts` holds the lines read so far and the candidate lines that failed to parse.
        """
        for line_number, line in enumerate(lines, start=1):
            counts["lines"] = line_number
            if self._prefilter and not self._prefilter.search(line):
                continue
            text = line.decode("utf-8", errors="replace")
            fields = parse_line(text, self._patterns)
            if fields:
                packages[fields["package"]] += 1
                matches.write(json.dumps({**fields, "line_number": line_number}).encode() + b"\n")
            elif not is_access_line(text):
                counts["unparsed"] += 1

    def _fail(self, stream_slice: Mapping[str, Any], line_number: int, error: Exception) -> None:
        """
        Record an object that failed to read. It sent no records and isn't marked as read, and its
        container's `completed_through` is held below it, so the next sync retries it.
        """
        failed = f"{stream_slice['prodstack']}/{stream_slice['name']}/{stream_slice['object']}"
        self.logger.error(f"Failed to read {failed} after {line_number} lines: {type(error).__name__}: {error}")
        self._failed.append(failed)
        key = self._state_key(stream_slice["prodstack"], stream_slice["name"])
        held = _day_before(stream_slice["date"])
        self._held[key] = min(self._held.get(key, held), held)

    def _mark_read(self, key: str, object_date: str, name: str, last_modified: str) -> None:
        """Mark an object as read, move `completed_through` forward as far as allowed, and drop the `read` entries it now covers."""
        state = self._state.get(key) or {"completed_through": "", "read": {}}
        # Objects are read in date order, so everything dated before this one is done, but
        # `completed_through` never enters the lookback window, where late objects may still land.
        # It also stays below any object of this container that failed in this sync.
        day_before = _day_before(object_date)
        limit = min(self._completed_through_limit, self._held.get(key, self._completed_through_limit))
        completed_through = max(state["completed_through"], min(day_before, limit))
        read = {n: v for n, v in state["read"].items() if (log_object_date(n) or "") > completed_through}
        read[name] = last_modified
        self._state[key] = {"completed_through": completed_through, "read": read}


def _day_before(yyyymmdd: str) -> str:
    """The day before a YYYYMMDD date, in the same format."""
    return (datetime.strptime(yyyymmdd, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
