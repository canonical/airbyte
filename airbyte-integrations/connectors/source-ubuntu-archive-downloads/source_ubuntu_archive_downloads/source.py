# Copyright (c) 2026 Canonical, all rights reserved.

import re
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
        names = [package_set["name"] for package_set in config["package_sets"]]
        if len(names) != len(set(names)):
            return False, "Package set names must be unique."

        for package_set in config["package_sets"]:
            if not STREAM_NAME_RE.match(package_set["name"]):
                return False, f"Package set name {package_set['name']!r} must be lowercase letters, digits and underscores."
            if not package_set["match"]:
                return False, f"Package set {package_set['name']!r} has no match patterns."

        try:
            store = make_store(config["storage"])
        except Exception as e:
            return False, f"Invalid storage config: {e}"

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
