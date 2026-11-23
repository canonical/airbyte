# Copyright (c) 2026 Canonical, all rights reserved.

"""
Generate mock Ubuntu archive log containers under integration_tests/mock_archives/.

The mocks assume the following about every container:
  - Each Swift container is a directory, with objects named <host dir>/<site>-access.log-YYYYMMDD.gz.
  - Log lines use this format:
      IP PORT - [DD/Mon/YYYY:HH:MM:SS +ZZZZ] "GET /path HTTP/x.x" STATUS BYTES "referer" "ua"
  - Containers also hold objects the connector must skip, such as error logs and today's live log.

Every access log has the same hand-written cases (see CASES), plus random noise lines that never
match a package set, so the expected records can be worked out from CASES alone. The output is
the same on every run.

The integration tests call `generate()` to write them to a temporary
directory. To write them under integration_tests/mock_archives/, for `make read` or to load into a
local Swift, run:

    python integration_tests/generate_mock_archives.py
"""

import gzip
import random
import shutil
from pathlib import Path


ROOT = Path(__file__).parent / "mock_archives"

# (container, object directory, site, arch for most cases)
SOURCES = [
    ("mock-archive-servers-a", "ubuntu-mirror-0", "archive.ubuntu.com", "amd64"),
    ("mock-archive-servers-a", "ubuntu-mirror-1", "archive.ubuntu.com", "amd64"),
    ("mock-archive-servers-b", "ubuntu-archive-0", "archive.ubuntu.com", "amd64"),
    ("mock-ports-servers", "ports-0", "ports.ubuntu.com", "arm64"),
    ("mock-cloud-mirrors", "cloud-mirror-0", "ec2.archive.ubuntu.com", "amd64"),  # real container names not known yet
]
DATES = ["20260501", "20260502", "20260503"]  # mock config starts at 2026-05-02
NOISE_LINES_PER_FILE = 200

POOL = "/ubuntu/pool/multiverse"

# (client, method, path, status, bytes, cuda match, rocm match). {arch} is filled per source.
CASES = [
    ("203.0.113.10", "GET", f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_{{arch}}.deb", 200, 171234, True, False),
    ("203.0.113.11", "GET", f"{POOL}/c/libcublas-13-0/libcublas-13-0_13.1.0.3-1_{{arch}}.deb", 200, 412345678, True, False),
    # %7e must be decoded to ~ in the version
    ("203.0.113.12", "GET", f"{POOL}/libn/libnvjpeg-13-0/libnvjpeg-13-0_13.0.1.9-1%7eubuntu24.04_{{arch}}.deb", 200, 3456789, True, False),
    (
        "203.0.113.13",
        "GET",
        f"{POOL}/n/nsight-compute-2025.3.1/nsight-compute-2025.3.1_2025.3.1.4-1_{{arch}}.deb",
        200,
        987654321,
        True,
        False,
    ),
    ("203.0.113.14", "GET", f"{POOL}/c/cuda-toolkit/cuda-toolkit_13.0.2-1_{{arch}}.deb", 200, 2890, True, False),
    ("203.0.113.15", "GET", f"{POOL}/c/cuda-toolkit-13/cuda-toolkit-13_13.0.2-1_{{arch}}.deb", 200, 2892, True, False),
    # 13.2 names match the same patterns; "-" bytes is stored as null
    ("203.0.113.16", "GET", f"{POOL}/c/cuda-nvcc-13-2/cuda-nvcc-13-2_13.2.51-1_{{arch}}.deb", 200, "-", True, False),
    ("2001:db8::17", "GET", f"{POOL}/c/cuda-nvcc-13-2/cuda-nvcc-13-2_13.2.51-1_{{arch}}.deb", 200, 61234567, True, False),
    # Ubuntu-packaged names count too
    (
        "203.0.113.31",
        "GET",
        f"{POOL}/n/nvidia-cuda-toolkit/nvidia-cuda-toolkit_12.0.140~12.0.1-4build4_{{arch}}.deb",
        200,
        345678,
        True,
        False,
    ),
    ("203.0.113.32", "GET", f"{POOL}/c/cuda-toolkit/libcublas12_12.4.127~12.4.1-1_{{arch}}.deb", 200, 45678901, True, False),
    ("203.0.113.18", "GET", f"{POOL}/r/rocm-smi-lib/rocm-smi-lib_6.4.1-1_{{arch}}.deb", 200, 812345, False, True),
    ("203.0.113.19", "GET", f"{POOL}/h/hip-runtime-amd/hip-runtime-amd_6.4.43482-1_{{arch}}.deb", 200, 23456789, False, True),
    # filtered out: status, method, not a .deb, pool directory decoy, near-miss names
    ("203.0.113.20", "GET", f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_{{arch}}.deb", 304, 0, False, False),
    ("203.0.113.21", "GET", f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_{{arch}}.deb", 404, 512, False, False),
    ("203.0.113.22", "GET", f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_{{arch}}.deb", 206, 65536, False, False),
    ("203.0.113.23", "HEAD", f"{POOL}/c/cuda-cudart-13-0/cuda-cudart-13-0_13.0.96-1_{{arch}}.deb", 200, 0, False, False),
    (
        "203.0.113.25",
        "GET",
        "/ubuntu/pool/universe/l/llvm-toolchain-13/libclang-13-dev_13.0.1-2ubuntu2_{arch}.deb",
        200,
        2345678,
        False,
        False,
    ),
    # the pool directory names a CUDA package, the downloaded file does not
    ("203.0.113.24", "GET", f"{POOL}/libn/libnvjpeg-13-1/vim-tiny_9.1.0-1_{{arch}}.deb", 200, 1234567, False, False),
    ("203.0.113.26", "GET", "/ubuntu/pool/main/c/curl/libcurl4t64_8.5.0-2ubuntu10_{arch}.deb", 200, 345678, False, False),
    ("203.0.113.28", "GET", f"{POOL}/f/fabric-manager/cuda-drivers-fabricmanager-570_570.133-1_{{arch}}.deb", 200, 56789, False, False),
    ("203.0.113.27", "GET", "/ubuntu/dists/noble/multiverse/binary-{arch}/Packages.gz", 200, 456789, False, False),
]
MALFORMED = "this line is not an access log entry"

NOISE_PACKAGES = ["firefox", "libc6", "python3.12", "openssl", "linux-firmware", "vim", "curl"]
USER_AGENT = "Debian APT-HTTP/1.3 (2.7.14build2)"


def access_line(client, method, path, status, size, when):
    return f'{client} 51234 - [{when} +0000] "{method} {path} HTTP/1.1" {status} {size} "-" "{USER_AGENT}"'


def access_log(rng, date, arch):
    day = f"{date[6:]}/May/{date[:4]}"
    lines = []
    for index, (client, method, path, status, size, *_) in enumerate(CASES):
        lines.append(access_line(client, method, path.format(arch=arch), status, size, f"{day}:{index:02d}:15:30"))
    lines.append(MALFORMED)
    for _ in range(NOISE_LINES_PER_FILE):
        package = rng.choice(NOISE_PACKAGES)
        path = f"/ubuntu/pool/main/{package[0]}/{package}/{package}_{rng.randint(1, 9)}.{rng.randint(0, 99)}-1_{arch}.deb"
        when = f"{day}:{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}"
        lines.append(
            access_line(f"198.51.100.{rng.randint(1, 254)}", "GET", path, rng.choice([200, 200, 200, 304]), rng.randint(1000, 10**8), when)
        )
    rng.shuffle(lines)
    return "\n".join(lines) + "\n"


def write_gzip(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the archives byte-for-byte reproducible
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(text.encode())


def generate(root: Path) -> None:
    """Write the mock containers under `root`, replacing anything already there."""
    shutil.rmtree(root, ignore_errors=True)
    rng = random.Random(2026)
    for container, directory, site, arch in SOURCES:
        base = root / container / directory
        for date in DATES:
            write_gzip(base / f"{site}-access.log-{date}.gz", access_log(rng, date, arch))
            write_gzip(base / f"{site}-error.log-{date}.gz", "[error] mock error log\n")
        # today's log, not rotated or compressed yet
        (base / f"{site}-access.log").write_text(
            access_line("203.0.113.30", "GET", CASES[0][2].format(arch=arch), 200, 1, "04/May/2026:00:00:01") + "\n"
        )


if __name__ == "__main__":
    generate(ROOT)
    print(f"wrote {sum(1 for p in ROOT.rglob('*') if p.is_file())} objects under {ROOT}")
