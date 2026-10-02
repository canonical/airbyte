import sys

from airbyte_cdk.entrypoint import launch

from .source import SourceNetsuiteSuiteql


def run() -> None:
    launch(SourceNetsuiteSuiteql(), sys.argv[1:])