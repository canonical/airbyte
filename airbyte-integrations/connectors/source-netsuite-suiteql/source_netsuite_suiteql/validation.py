# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import IncompleteIncrementalConfigurationError, InvalidCursorParameterIndexError


INCREMENTAL_FIELDS = ("primary_key", "cursor_field", "cursor_parameter_index")


@dataclass(frozen=True)
class IncrementalQueryConfiguration:
    query_name: str
    parameters: list[Any]
    cursor_parameter_index: int

    @classmethod
    def from_query(cls, query: Mapping[str, Any]) -> "IncrementalQueryConfiguration | None":
        configured_fields = set(query).intersection(INCREMENTAL_FIELDS)

        if not configured_fields:
            return None

        if len(configured_fields) != len(INCREMENTAL_FIELDS):
            raise IncompleteIncrementalConfigurationError(query["name"])

        return cls(
            query_name=query["name"],
            parameters=query.get("parameters", []),
            cursor_parameter_index=query["cursor_parameter_index"],
        )

    def validate(self) -> None:
        if not 0 <= self.cursor_parameter_index < len(self.parameters):
            raise InvalidCursorParameterIndexError(self.query_name)


class SuiteQLQueryValidator:
    def __init__(self, query: Mapping[str, Any]):
        self.query = query

    def validate(self) -> None:
        incremental_config = IncrementalQueryConfiguration.from_query(self.query)
        if incremental_config:
            incremental_config.validate()
