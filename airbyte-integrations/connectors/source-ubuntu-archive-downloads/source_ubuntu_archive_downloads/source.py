# Copyright (c) 2026 Canonical, all rights reserved.

import re
from datetime import datetime
from typing import Any, List, Mapping, Tuple

from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from source_ubuntu_archive_downloads.store import make_store
from source_ubuntu_archive_downloads.streams import PackageSetStream


STREAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SourceUbuntuArchiveDownloads(AbstractSource):
    """Airbyte source with one stream per configured package set."""

    def check_connection(self, logger, config) -> Tuple[bool, Any]:
        """Check that the package sets are valid and that every container can be read through its Prodstack's store."""
        # Each package set becomes a stream and a destination table, so names must be unique.
        names = [package_set["name"] for package_set in config["package_sets"]]
        if len(names) != len(set(names)):
            return False, "Package set names must be unique."

        # Names are used as table names, so keep them to characters every destination accepts.
        # A set with no patterns would match nothing.
        for package_set in config["package_sets"]:
            if not STREAM_NAME_RE.match(package_set["name"]):
                return False, f"Package set name {package_set['name']!r} must be lowercase letters, digits and underscores."
            if not package_set["match"]:
                return False, f"Package set {package_set['name']!r} has no match patterns."

        # The spec only checks the pattern of `start_date`, so a date such as 2026-02-30 gets through.
        try:
            datetime.strptime(config["start_date"], "%Y-%m-%d")
        except ValueError:
            return False, f"Start date {config['start_date']!r} is not a valid date in the format YYYY-MM-DD."

        # State is kept per Prodstack and container, so the same container listed twice would be read twice.
        containers = [(container["prodstack"], container["name"]) for container in config["containers"]]
        repeated = sorted({f"{p}/{n}" for p, n in containers if containers.count((p, n)) > 1})
        if repeated:
            return False, f"Containers are listed more than once: {', '.join(repeated)}."

        # Build the stores, which fails for example when a Prodstack has more than one endpoint.
        try:
            store = make_store(config["storage"])
        except Exception as e:
            return False, f"Invalid storage config: {e}"

        # Log in to each Prodstack and check that each container, and its `_segments` container if any, can be read.
        for container in config["containers"]:
            try:
                store.for_prodstack(container["prodstack"]).assert_readable(container["name"])
            except Exception as e:
                return False, f"Unable to read container {container['name']!r} on {container['prodstack']}: {e}"

        return True, None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        """Build one `PackageSetStream` per package set. They all share the same containers and store."""
        store = make_store(config["storage"])
        return [
            PackageSetStream(
                name=package_set["name"],
                patterns=package_set["match"],
                containers=config["containers"],
                start_date=config["start_date"],
                store=store,
                lookback_days=config.get("lookback_days", 2),
            )
            for package_set in config["package_sets"]
        ]
