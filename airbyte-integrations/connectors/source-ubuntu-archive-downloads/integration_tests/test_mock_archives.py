# Copyright (c) 2026 Canonical, all rights reserved.

"""
Run check, discover and read against the mock archives, generated once per test session.

Expected values come from the CASES table in generate_mock_archives.py.
"""

import gzip
import json
import logging
from collections import Counter
from pathlib import Path

import pytest
from generate_mock_archives import CASES, SOURCES, generate
from source_ubuntu_archive_downloads.parser import line_prefilter, matches_any, parse_line
from source_ubuntu_archive_downloads.source import SourceUbuntuArchiveDownloads

from airbyte_cdk.models.airbyte_protocol_serializers import ConfiguredAirbyteCatalogSerializer
from airbyte_cdk.test.entrypoint_wrapper import discover, read


HERE = Path(__file__).parent
FILES_FROM_START_DATE = len(SOURCES) * 2  # 20260502 and 20260503
LOGGER = logging.getLogger("airbyte")


@pytest.fixture(scope="session")
def mock_archives(tmp_path_factory):
    root = tmp_path_factory.mktemp("mock") / "mock_archives"
    generate(root)
    return root


@pytest.fixture
def config(mock_archives):
    config = json.loads((HERE / "mock_config.json").read_text())
    config["storage"]["path"] = str(mock_archives)
    return config


@pytest.fixture
def catalog():
    return ConfiguredAirbyteCatalogSerializer.load(json.loads((HERE / "configured_catalog.json").read_text()))


def records_by_stream(output):
    by_stream = {}
    for message in output.records:
        by_stream.setdefault(message.record.stream, []).append(message.record.data)
    return by_stream


def test_check(config):
    status, _ = SourceUbuntuArchiveDownloads().check_connection(LOGGER, config)
    assert status


def test_check_fails_for_a_missing_container(config):
    config["containers"].append({"name": "prod-does-not-exist", "source": "archive_server", "prodstack": "ps5"})
    status, message = SourceUbuntuArchiveDownloads().check_connection(LOGGER, config)
    assert not status and "prod-does-not-exist" in message


def test_check_fails_for_a_prodstack_without_a_swift_endpoint(config):
    config["storage"] = {
        "type": "swift",
        "endpoints": [
            {"prodstack": "ps6", "auth_url": "https://keystone.invalid/v3", "username": "u", "password": "p", "project_name": "x"}
        ],
    }
    status, message = SourceUbuntuArchiveDownloads().check_connection(LOGGER, config)
    assert not status and "'ps5'" in message


def test_read_logs_counts_per_object_and_matched_packages_per_stream(config, catalog):
    output = read(SourceUbuntuArchiveDownloads(), config, catalog)
    messages = [m.log.message for m in output.logs if m.log]
    per_object = [m for m in messages if m.startswith("Read ") and "matched rows" in m]
    assert len(per_object) == 2 * FILES_FROM_START_DATE
    assert all("lines," in m and "failed to parse" in m for m in per_object)
    summaries = [m for m in messages if " matched packages: " in m]
    assert [m.split()[1] for m in summaries] == ["cuda", "rocm"]
    assert "'cuda-nvcc-13-2': " in summaries[0]


def test_discover_has_one_stream_per_package_set(config):
    catalog = discover(SourceUbuntuArchiveDownloads(), config).catalog.catalog
    assert catalog is not None
    streams = catalog.streams
    assert [s.name for s in streams] == ["cuda", "rocm"]
    assert streams[0].source_defined_primary_key == [["prodstack"], ["container"], ["log_object"], ["line_number"]]


def test_read_emits_one_record_per_matching_download(config, catalog):
    by_stream = records_by_stream(read(SourceUbuntuArchiveDownloads(), config, catalog))

    assert len(by_stream["cuda"]) == FILES_FROM_START_DATE * sum(case[5] for case in CASES)
    assert len(by_stream["rocm"]) == FILES_FROM_START_DATE * sum(case[6] for case in CASES)
    assert {r["arch"] for r in by_stream["cuda"] if r["container"] == "mock-ports-servers"} == {"arm64"}
    assert min(r["timestamp"] for r in by_stream["cuda"]).startswith("2026-05-02")
    keys = Counter((r["prodstack"], r["container"], r["log_object"], r["line_number"]) for r in by_stream["cuda"])
    assert max(keys.values()) == 1


def test_prefilter_never_drops_a_matching_line(config, mock_archives):
    for package_set in config["package_sets"]:
        patterns = package_set["match"]
        prefilter = line_prefilter(patterns)
        assert prefilter is not None
        for path in mock_archives.rglob("*access.log-*.gz"):
            for line in gzip.open(path, "rb"):
                if parse_line(line.decode(), patterns):
                    assert prefilter.search(line)


@pytest.mark.parametrize(
    "package, matches",
    [
        ("cuda-nvcc-13-1", True),
        ("cuda-nvcc-14-0", True),
        ("cuda-toolkit-13-1-config-common", True),
        ("cuda-toolkit-14", True),
        ("nvidia-cuda-toolkit", True),
        ("nvidia-cuda-dev", True),
        ("libcublas12", True),
        ("libcudart12", True),
        ("libnppc12", True),
        ("libnvrtc13", True),
        ("libnvrtc-builtins13.0", True),
        ("nsight-compute", True),
        ("gds-tools", True),
        ("libcurl4t64", False),
        ("libcups2t64", False),
        ("libcunit1", False),
        ("libclang-13-dev", False),
        ("cuda-drivers-fabricmanager-570", False),
        ("libgloo-cuda-0", False),
    ],
)
def test_cuda_patterns(config, package, matches):
    assert matches_any(package, config["package_sets"][0]["match"]) is matches


def test_every_record_carries_its_source_and_prodstack(config, catalog):
    records = records_by_stream(read(SourceUbuntuArchiveDownloads(), config, catalog))["cuda"]
    assert {(r["container"], r["source"], r["prodstack"]) for r in records} == {
        ("mock-archive-servers-a", "archive_server", "ps5"),
        ("mock-archive-servers-b", "archive_server", "ps6"),
        ("mock-ports-servers", "ports_server", "ps6"),
        ("mock-cloud-mirrors", "cloud_mirror", "ps5"),
    }


def test_no_client_ip_reaches_a_record(config, catalog):
    output = read(SourceUbuntuArchiveDownloads(), config, catalog)
    serialized = json.dumps([m.record.data for m in output.records if m.record])
    for client, *_ in CASES:
        assert client not in serialized


def test_daily_totals_per_package(config, catalog):
    """A daily total for one package is a GROUP BY over its records."""
    records = records_by_stream(read(SourceUbuntuArchiveDownloads(), config, catalog))["cuda"]
    nvcc = [r for r in records if r["timestamp"].startswith("2026-05-02") and r["package"] == "cuda-nvcc-13-2" and r["arch"] == "amd64"]
    # two matching cases per file (one with "-" bytes), four amd64 files per day
    assert len(nvcc) == 8
    assert sum(r.get("bytes") or 0 for r in nvcc) == 4 * 61234567


def test_incremental_sync_resumes_after_the_last_object(config, catalog):
    first = read(SourceUbuntuArchiveDownloads(), config, catalog)
    last_state = {m.state.stream.stream_descriptor.name: m.state for m in first.state_messages if m.state and m.state.stream}
    state = list(last_state.values())
    assert len(state) == 2
    second = read(SourceUbuntuArchiveDownloads(), config, catalog, state=state)
    assert second.records == []


def test_unreadable_object_fails_the_sync_after_the_rest_is_read(config, catalog, tmp_path):
    """Through the CDK's own read loop: the failure raised once a stream's slices run out must reach Airbyte."""
    generate(tmp_path / "mock_archives")
    config["storage"]["path"] = str(tmp_path / "mock_archives")
    bad = tmp_path / "mock_archives/mock-ports-servers/ports-0/ports.ubuntu.com-access.log-20260502.gz"
    bad.write_bytes(bad.read_bytes()[:-20])

    output = read(SourceUbuntuArchiveDownloads(), config, catalog, expecting_exception=True)

    by_stream = records_by_stream(output)
    per_file = sum(case[5] for case in CASES)
    assert len(by_stream["cuda"]) == (FILES_FROM_START_DATE - 1) * per_file
    assert not any(r["log_object"] == "ports-0/ports.ubuntu.com-access.log-20260502.gz" for r in by_stream["cuda"])
    errors = [m.trace.error for m in output.errors if m.trace and m.trace.error]
    assert any("could not read 1 log objects" in e.message for e in errors)
