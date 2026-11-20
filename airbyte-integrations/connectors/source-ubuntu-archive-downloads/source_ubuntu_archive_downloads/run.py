# Copyright (c) 2026 Canonical, all rights reserved.

import sys

from airbyte_cdk.entrypoint import launch
from source_ubuntu_archive_downloads.source import SourceUbuntuArchiveDownloads


def run():
    """Hand the command-line arguments (spec, check, discover or read) to the CDK."""
    source = SourceUbuntuArchiveDownloads()
    launch(source, sys.argv[1:])
