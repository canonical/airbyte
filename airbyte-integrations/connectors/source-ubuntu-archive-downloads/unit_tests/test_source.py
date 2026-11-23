# Copyright (c) 2026 Canonical, all rights reserved.

import logging

from source_ubuntu_archive_downloads.source import SourceUbuntuArchiveDownloads


LOGGER = logging.getLogger("airbyte")


def config(tmp_path, **overrides):
    (tmp_path / "logs").mkdir(exist_ok=True)
    return {
        "storage": {"type": "local", "path": str(tmp_path)},
        "containers": [{"name": "logs", "source": "archive_server", "prodstack": "ps5"}],
        "start_date": "2026-05-02",
        "package_sets": [{"name": "cuda", "match": ["cuda-*"]}],
        **overrides,
    }


def test_valid_config_passes(tmp_path):
    assert SourceUbuntuArchiveDownloads().check_connection(LOGGER, config(tmp_path)) == (True, None)


def test_start_date_must_be_a_real_date(tmp_path):
    ok, message = SourceUbuntuArchiveDownloads().check_connection(LOGGER, config(tmp_path, start_date="2026-13-45"))
    assert not ok and "2026-13-45" in message


def test_a_container_listed_twice_is_rejected(tmp_path):
    container = {"name": "logs", "source": "archive_server", "prodstack": "ps5"}
    ok, message = SourceUbuntuArchiveDownloads().check_connection(LOGGER, config(tmp_path, containers=[container, container]))
    assert not ok and "ps5/logs" in message


def test_same_container_name_on_two_prodstacks_is_allowed(tmp_path):
    containers = [{"name": "logs", "source": "cloud_mirror", "prodstack": p} for p in ("ps5", "ps6")]
    assert SourceUbuntuArchiveDownloads().check_connection(LOGGER, config(tmp_path, containers=containers)) == (True, None)
