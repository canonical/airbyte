# Copyright (c) 2026 Canonical, all rights reserved.

"""
Parse and filter Ubuntu archive Apache access log lines.

A line is kept if it's a GET request that returned HTTP 200 for a `name_version_arch.deb` file.
206 (partial content) responses are left out: they're mostly resumes of a download whose first
request was already logged as a 200, so counting them would count one download more than once.
Only the fields we store are captured, never the client IP.

Expected log format, as observed in the real archive logs:
  IP PORT - [DD/Mon/YYYY:HH:MM:SS +ZZZZ] "GET /path HTTP/x.x" STATUS BYTES "referer" "ua" ...

This is Apache's Combined Log Format (https://httpd.apache.org/docs/2.4/logs.html#combined) with
the client port in the second field, where Combined has the ident `-`. The second and third fields
are matched loosely, so plain Combined lines parse too. For example:
  203.0.113.10 51234 - [02/May/2026:07:15:30 +0000] "GET /ubuntu/pool/multiverse/c/cuda-toolkit/cuda-toolkit_13.0.2-1_amd64.deb HTTP/1.1" 200 2890 "-" "Debian APT-HTTP/1.3 (2.7.14build2)"
"""

import re
from datetime import datetime
from fnmatch import fnmatchcase
from typing import Iterable, Mapping, Optional, Pattern
from urllib.parse import unquote


LOG_RE = re.compile(
    r"^\S+"  # IP, not captured
    r" \S+"  # port or ident
    r" \S+"  # ident or auth user
    r" \[([^\]]+)\]"  # [DD/Mon/YYYY:HH:MM:SS +ZZZZ] -> group 1
    r' "(\S+) (\S+) HTTP/[^"]*"'  # "METHOD path proto" -> groups 2, 3
    r" (\d+)"  # status -> group 4
    r" (\d+|-)"  # bytes or - -> group 5
)

# Debian package filename at the end of the path: name_version_arch.deb. Each part is one or more
# characters other than `/` and `_`, since Debian names, versions and arches never contain `_`.
# For example `/ubuntu/pool/.../libnvjpeg-13-0_13.0.1.9-1~ubuntu24.04_amd64.deb` gives
# ("libnvjpeg-13-0", "13.0.1.9-1~ubuntu24.04", "amd64"). unquote() runs first, so `%7e` becomes `~`.
DEB_RE = re.compile(r"/([^/]+)_([^_]+)_([^_]+)\.deb$", re.IGNORECASE)

# Dated access log objects, e.g. ubuntu-mirror-0/archive.ubuntu.com-access.log-20250223.gz
LOG_OBJECT_RE = re.compile(r"access[_.-]log[_.-](\d{8})\.gz$")

APACHE_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


def log_object_date(name: str) -> Optional[str]:
    """Return the YYYYMMDD date of an access log object, or None if it isn't one."""
    match = LOG_OBJECT_RE.search(name)
    return match.group(1) if match else None


def matches_any(package: str, patterns: Iterable[str]) -> bool:
    """Whether the package name matches any of the glob patterns. Matching is case-sensitive, like Debian package names."""
    return any(fnmatchcase(package, pattern) for pattern in patterns)


def line_prefilter(patterns: Iterable[str]) -> Optional[Pattern[bytes]]:
    """
    Build a quick check to run on each raw line before parsing it.

    A line can only match if its path contains `/` followed by the fixed start of a pattern, such
    as `/cuda-` for `cuda-*`. Most lines fail this check, so they skip decoding and full parsing.
    Returns None if a pattern starts with a wildcard or an encodable character, since then every
    line has to be parsed.
    """
    prefixes = {re.split(r"[^A-Za-z0-9._-]", pattern, maxsplit=1)[0] for pattern in patterns}
    if "" in prefixes:
        return None
    return re.compile(b"/(?:" + b"|".join(re.escape(prefix.encode()) for prefix in sorted(prefixes)) + b")")


def parse_time(raw_time: str) -> Optional[datetime]:
    """Parse an Apache log time, or return None if it's not in the expected format."""
    try:
        return datetime.strptime(raw_time, APACHE_TIME_FORMAT)
    except ValueError:
        return None


def is_access_line(line: str) -> bool:
    """Whether a line is in the expected log format, time included, so a change in format gets noticed."""
    match = LOG_RE.match(line)
    return bool(match) and parse_time(match.group(1)) is not None


def parse_line(line: str, patterns: Iterable[str]) -> Optional[Mapping[str, object]]:
    """Return the fields we store for a matching download, or None if the line doesn't match."""
    match = LOG_RE.match(line)
    if not match:
        return None
    raw_time, method, url_path, status, raw_bytes = match.groups()
    if method != "GET" or status != "200":
        return None
    deb = DEB_RE.search(unquote(url_path))
    if not deb:
        return None
    package, version, arch = deb.groups()
    if not matches_any(package, patterns):
        return None
    timestamp = parse_time(raw_time)
    if timestamp is None:
        return None
    return {
        "timestamp": timestamp.isoformat(),
        "package": package,
        "version": version,
        "arch": arch,
        "bytes": None if raw_bytes == "-" else int(raw_bytes),
    }
