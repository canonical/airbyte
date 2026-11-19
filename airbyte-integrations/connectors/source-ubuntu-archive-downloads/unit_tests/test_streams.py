# Copyright (c) 2026 Canonical, all rights reserved.

import gzip
import io
import os
from datetime import date
from typing import List, Mapping

import pytest
from source_ubuntu_archive_downloads.store import LocalStore, _ChunkReader
from source_ubuntu_archive_downloads.streams import PackageSetStream

from airbyte_cdk.models.airbyte_protocol import SyncMode


CONTAINER = "mock-archive-servers-a"
KEY = f"ps5/{CONTAINER}"
MATCH = '203.0.113.10 51234 - [{day}/May/2026:07:15:30 +0000] "GET /ubuntu/pool/multiverse/c/cuda-toolkit/cuda-toolkit_13.0.2-1_amd64.deb HTTP/1.1" 200 2890 "-" "apt"'
NOISE = '198.51.100.1 51234 - [{day}/May/2026:07:15:31 +0000] "GET /ubuntu/pool/main/v/vim/vim_9.1-1_amd64.deb HTTP/1.1" 200 1234 "-" "apt"'


def write_log(root, name, lines):
    path = root / CONTAINER / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write("\n".join(lines) + "\n")
    return path


@pytest.fixture
def root(tmp_path):
    write_log(tmp_path, "ubuntu-mirror-0/archive.ubuntu.com-access.log-20260501.gz", [MATCH.format(day="01")])
    write_log(tmp_path, "ubuntu-mirror-0/archive.ubuntu.com-access.log-20260502.gz", [NOISE.format(day="02"), MATCH.format(day="02")])
    write_log(tmp_path, "ubuntu-mirror-1/archive.ubuntu.com-access.log-20260502.gz", [MATCH.format(day="02")])
    write_log(tmp_path, "ubuntu-mirror-0/archive.ubuntu.com-error.log-20260502.gz", ["[error] x"])
    (tmp_path / CONTAINER / "ubuntu-mirror-0/archive.ubuntu.com-access.log").write_text(MATCH.format(day="03"))
    return tmp_path


M0 = "ubuntu-mirror-0/archive.ubuntu.com-access.log-{}.gz"
M1 = "ubuntu-mirror-1/archive.ubuntu.com-access.log-{}.gz"


def make_stream(root, start_date="2026-05-02", today=date(2026, 5, 4), lookback_days=1, state=None):
    stream = PackageSetStream(
        "cuda",
        ["cuda-toolkit"],
        [{"name": CONTAINER, "source": "archive_server", "prodstack": "ps5"}],
        start_date,
        LocalStore(str(root)),
        lookback_days=lookback_days,
        today=today,
    )
    if state is not None:
        stream.state = state
    return stream


def read_all(stream, sync_mode=SyncMode.incremental):
    records = []
    for stream_slice in stream.stream_slices(sync_mode=sync_mode):
        records.extend(stream.read_records(sync_mode=sync_mode, stream_slice=stream_slice))
    return records


def test_slices_are_dated_access_logs_from_start_date_in_order(root):
    slices = list(make_stream(root).stream_slices(sync_mode=SyncMode.incremental))
    assert [s["object"] for s in slices if s] == [
        "ubuntu-mirror-0/archive.ubuntu.com-access.log-20260502.gz",
        "ubuntu-mirror-1/archive.ubuntu.com-access.log-20260502.gz",
    ]


def test_records_are_keyed_by_container_object_and_line(root):
    records = read_all(make_stream(root))
    assert [(r["log_object"], r["line_number"]) for r in records] == [
        ("ubuntu-mirror-0/archive.ubuntu.com-access.log-20260502.gz", 2),
        ("ubuntu-mirror-1/archive.ubuntu.com-access.log-20260502.gz", 1),
    ]
    assert {(r["container"], r["source"], r["prodstack"]) for r in records} == {(CONTAINER, "archive_server", "ps5")}


def test_state_keeps_the_lookback_window_and_next_sync_reads_only_new_objects(root):
    stream = make_stream(root)
    read_all(stream)
    # today 2026-05-04, lookback 1 day: 05-03 onwards is in the window, so `completed_through` stops at 05-02
    assert stream.state[KEY]["completed_through"] == "20260501"
    assert set(stream.state[KEY]["read"]) == {M0.format("20260502"), M1.format("20260502")}

    write_log(root, M0.format("20260503"), [MATCH.format(day="03")])
    next_sync = make_stream(root, state=stream.state)
    assert [r["log_object"] for r in read_all(next_sync)] == [M0.format("20260503")]
    assert next_sync.state[KEY]["completed_through"] == "20260502"
    assert set(next_sync.state[KEY]["read"]) == {M0.format("20260503")}


def test_late_object_inside_the_window_is_still_read(root):
    write_log(root, M0.format("20260503"), [MATCH.format(day="03")])
    first = make_stream(root)
    read_all(first)

    # mirror-1's 05-03 log lands after mirror-0's 05-03 was read
    write_log(root, M1.format("20260503"), [MATCH.format(day="03")])
    late = make_stream(root, state=first.state)
    assert [r["log_object"] for r in read_all(late)] == [M1.format("20260503")]


def test_late_object_older_than_the_window_is_skipped(root):
    write_log(root, M0.format("20260510"), [MATCH.format(day="10")])
    first = make_stream(root, today=date(2026, 5, 12))
    read_all(first)
    assert first.state[KEY]["completed_through"] == "20260509"

    write_log(root, M1.format("20260505"), [MATCH.format(day="05")])
    assert read_all(make_stream(root, today=date(2026, 5, 12), state=first.state)) == []


def test_full_refresh_ignores_state(root):
    stream = make_stream(root)
    stream.state = {KEY: {"completed_through": "20260509", "read": {}}}
    assert len(read_all(stream, SyncMode.full_refresh)) == 2


def test_failed_object_does_not_advance_state_and_is_read_again(root):
    good = write_log(root, "ubuntu-mirror-0/archive.ubuntu.com-access.log-20260503.gz", [MATCH.format(day="03")] * 50)
    (root / CONTAINER / "ubuntu-mirror-0/archive.ubuntu.com-access.log-20260504.gz").write_bytes(good.read_bytes()[:-20])

    stream = make_stream(root, start_date="2026-05-03", today=date(2026, 5, 20))
    with pytest.raises(EOFError):
        read_all(stream)
    assert stream.state[KEY]["completed_through"] == "20260502"
    assert set(stream.state[KEY]["read"]) == {M0.format("20260503")}

    retry = make_stream(root, start_date="2026-05-03", today=date(2026, 5, 20), state=stream.state)
    assert [s["date"] for s in retry.stream_slices(sync_mode=SyncMode.incremental) if s] == ["20260504"]


def test_reading_an_object_twice_gives_the_same_keys(root):
    first = read_all(make_stream(root))
    second = read_all(make_stream(root))
    assert first == second


def test_object_changed_after_it_was_read_is_read_again(root):
    first = make_stream(root)
    assert len(read_all(first)) == 2

    # the upload was incomplete and got replaced with a longer file
    path = write_log(root, M0.format("20260502"), [NOISE.format(day="02"), MATCH.format(day="02"), MATCH.format(day="02")])
    os.utime(path, ns=(10**18, 10**18))

    again = read_all(make_stream(root, state=first.state))
    assert [(r["log_object"], r["line_number"]) for r in again] == [(M0.format("20260502"), 2), (M0.format("20260502"), 3)]


def test_container_without_dated_access_logs_is_reported(tmp_path, caplog):
    (tmp_path / CONTAINER).mkdir()
    (tmp_path / CONTAINER / "mirror-access-2026-05-03.log.gz").write_bytes(b"")

    assert list(make_stream(tmp_path).stream_slices(sync_mode=SyncMode.incremental)) == []
    assert f"Container {CONTAINER} has 1 objects" in caplog.text


def test_candidate_lines_in_another_format_are_counted_in_the_logs(root, caplog):
    other_format = "2026-05-03 07:15:30 GET /ubuntu/pool/multiverse/c/cuda-toolkit/cuda-toolkit_13.0.2-1_amd64.deb 200 2890"
    write_log(root, M0.format("20260503"), [other_format, MATCH.format(day="03"), other_format, NOISE.format(day="03")])

    records = read_all(make_stream(root, start_date="2026-05-03"))

    assert len(records) == 1
    assert f"2 candidate lines in {CONTAINER}/{M0.format('20260503')}" in caplog.text


def test_filtered_access_lines_are_not_counted_as_another_format(root, caplog):
    head = MATCH.format(day="03").replace('"GET ', '"HEAD ')
    write_log(root, M0.format("20260503"), [head, MATCH.format(day="03").replace(" 200 ", " 304 ")])

    assert read_all(make_stream(root, start_date="2026-05-03")) == []
    assert "not in the expected log format" not in caplog.text


def test_chunk_reader_streams_gzip_across_chunk_boundaries():
    data = gzip.compress(("\n".join(MATCH.format(day="02") for _ in range(1000)) + "\n").encode())
    chunks = iter([data[i : i + 7] for i in range(0, len(data), 7)])
    with gzip.open(io.BufferedReader(_ChunkReader(chunks)), "rt") as lines:
        assert sum(1 for _ in lines) == 1000


class StorePerProdstack:
    """A `LocalStore` per Prodstack, like `SwiftStores` with one endpoint each."""

    def __init__(self, roots):
        self._stores = {prodstack: LocalStore(str(root)) for prodstack, root in roots.items()}

    def for_prodstack(self, prodstack):
        return self._stores[prodstack]


def test_same_container_name_on_two_prodstacks_is_tracked_separately(tmp_path):
    for prodstack in ("ps5", "ps6"):
        for day in ("02", "03"):
            write_log(tmp_path / prodstack, f"{prodstack}-mirror-0/archive.ubuntu.com-access.log-202605{day}.gz", [MATCH.format(day=day)])
    containers: List[Mapping[str, str]] = [
        {"name": CONTAINER, "source": "cloud_mirror", "prodstack": prodstack} for prodstack in ("ps5", "ps6")
    ]
    store = StorePerProdstack({"ps5": tmp_path / "ps5", "ps6": tmp_path / "ps6"})
    stream = PackageSetStream("cuda", ["cuda-toolkit"], containers, "2026-05-02", store, lookback_days=1, today=date(2026, 5, 20))

    # reading ps5 first must not mark ps6's 05-02 log as done
    records = read_all(stream)
    assert sorted((r["prodstack"], r["log_object"][-11:-3]) for r in records) == [
        ("ps5", "20260502"),
        ("ps5", "20260503"),
        ("ps6", "20260502"),
        ("ps6", "20260503"),
    ]
    assert set(stream.state) == {f"ps5/{CONTAINER}", f"ps6/{CONTAINER}"}
