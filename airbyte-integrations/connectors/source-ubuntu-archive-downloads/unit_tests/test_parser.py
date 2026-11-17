# Copyright (c) 2026 Canonical, all rights reserved.

import pytest
from source_ubuntu_archive_downloads.parser import line_prefilter, log_object_date, matches_any, parse_line


CUDA = ["cuda-*-13-*", "libcu*-13-*", "libnv*-13-*", "nsight-compute-*", "cuda-toolkit", "cuda-toolkit-13"]
POOL = "/ubuntu/pool/multiverse"


def line(path, status=200, size: "int | str" = 1000, method="GET", client="203.0.113.10"):
    return f'{client} 51234 - [02/May/2026:07:15:30 +0000] "{method} {path} HTTP/1.1" {status} {size} "-" "Debian APT-HTTP/1.3"'


def test_matching_download_keeps_only_the_stored_fields():
    record = parse_line(line(f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_amd64.deb", size=171234), CUDA)
    assert record == {
        "timestamp": "2026-05-02T07:15:30+00:00",
        "package": "cuda-cudart-13-0",
        "version": "13.0.96-1",
        "arch": "amd64",
        "bytes": 171234,
    }


def test_client_ip_is_never_stored():
    record = parse_line(line(f"{POOL}/c/cuda-toolkit/cuda-toolkit_13.0.2-1_amd64.deb", client="2001:db8::17"), CUDA)
    assert "2001:db8::17" not in repr(record)


def test_url_encoded_version_is_decoded():
    record = parse_line(line(f"{POOL}/libn/libnvjpeg-13-0/libnvjpeg-13-0_13.0.1.9-1%7eubuntu24.04_amd64.deb"), CUDA)
    assert record is not None
    assert record["version"] == "13.0.1.9-1~ubuntu24.04"


def test_dash_bytes_is_null():
    record = parse_line(line(f"{POOL}/c/cuda-toolkit/cuda-toolkit_13.0.2-1_amd64.deb", size="-"), CUDA)
    assert record is not None
    assert record["bytes"] is None


@pytest.mark.parametrize(
    "text",
    [
        line(f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_amd64.deb", status=304),
        line(f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_amd64.deb", status=206),
        line(f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_amd64.deb", method="HEAD"),
        line("/ubuntu/dists/noble/multiverse/binary-amd64/Packages.gz"),
        # the pool directory names a CUDA package, the downloaded file does not
        line(f"{POOL}/libn/libnvjpeg-13-1/libnvjpeg12_12.4.0-1_amd64.deb"),
        line("/ubuntu/pool/universe/l/llvm-toolchain-13/libclang-13-dev_13.0.1-2ubuntu2_amd64.deb"),
        line(f"{POOL}/n/nvidia-cuda-toolkit/nvidia-cuda-toolkit_12.0.140~12.0.1-4build4_amd64.deb"),
        "this line is not an access log entry",
    ],
    ids=["304", "206", "head", "not-deb", "pool-decoy", "libclang", "nvidia-cuda-toolkit", "malformed"],
)
def test_filtered_out(text):
    assert parse_line(text, CUDA) is None


def test_patterns_match_the_whole_name():
    assert matches_any("cuda-nvcc-13-2", CUDA)
    assert matches_any("cuda-toolkit-13", CUDA)
    assert not matches_any("cuda-toolkit-13-extra-tools", ["cuda-toolkit-13"])
    assert not matches_any("libclang-13-dev", CUDA)


@pytest.mark.parametrize(
    "name, date",
    [
        ("ubuntu-mirror-0/archive.ubuntu.com-access.log-20250223.gz", "20250223"),
        ("ports.ubuntu.com-access_log.20250223.gz", "20250223"),
        ("ubuntu-mirror-0/archive.ubuntu.com-access.log", None),
        ("ubuntu-mirror-0/archive.ubuntu.com-error.log-20250223.gz", None),
        ("ubuntu-mirror-0/archive.ubuntu.com-access.log-20250223", None),
    ],
)
def test_log_object_date(name, date):
    assert log_object_date(name) == date


def test_prefilter_keeps_every_candidate_and_drops_other_lines():
    prefilter = line_prefilter(CUDA)
    assert prefilter is not None
    assert prefilter.search(line(f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_amd64.deb").encode())
    assert prefilter.search(line(f"{POOL}/n/nsight-compute-2025.3.1/nsight-compute-2025.3.1_2025.3.1.4-1_amd64.deb").encode())
    assert not prefilter.search(line("/ubuntu/pool/main/v/vim/vim_9.1-1_amd64.deb").encode())


def test_prefilter_is_off_when_a_pattern_has_no_literal_start():
    assert line_prefilter(["*-cuda"]) is None
